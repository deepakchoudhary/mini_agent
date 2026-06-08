#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from core import run_agent
from graders import grade_task
from instrumentation import EvalTracer
from metrics import summarize
from providers import create_provider


BENCHMARKS_DIR = ROOT / "benchmarks"
DEFAULT_OUTPUT = ROOT / "metrics" / "latest.json"
HISTORY_OUTPUT = ROOT / "metrics" / "history.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_eval",
        description="Run orchestration evals for mini_agent.",
    )
    parser.add_argument("--mode", choices=["local", "remote"], default="local")
    parser.add_argument("--local-model", default="qwen2.5")
    parser.add_argument("--provider", choices=["openai", "anthropic", "gemini"], default="openai")
    parser.add_argument("--model", default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Hard per-task timeout. Latency SLOs are reported separately from correctness.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate benchmark files without calling an LLM.")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    tasks = load_tasks()
    tasks = filter_tasks(tasks, category=args.category, task_id=args.task_id)

    if args.dry_run:
        payload = {
            "dry_run": True,
            "task_count": len(tasks),
            "categories": sorted({task["category"] for task in tasks}),
            "task_ids": [task["id"] for task in tasks],
        }
        print(json.dumps(payload, indent=2))
        return

    provider = build_provider(args)
    results = [
        run_one(task, provider, quiet=args.quiet, timeout_seconds=args.timeout_seconds)
        for task in tasks
    ]
    summary = summarize(results)
    payload = {
        "run_started_at": int(time.time()),
        "mode": args.mode,
        "model": str(provider),
        "summary": summary,
        "results": results,
    }

    write_outputs(payload, Path(args.output))
    print_report(payload)

    if summary["failed_tasks"]:
        sys.exit(1)


def load_tasks() -> list[dict[str, Any]]:
    files = [
        BENCHMARKS_DIR / "reasoning_tasks.json",
        BENCHMARKS_DIR / "single_tool_tasks.json",
        BENCHMARKS_DIR / "multi_step_tasks.json",
        BENCHMARKS_DIR / "recovery_tasks.json",
        BENCHMARKS_DIR / "advanced_tasks.json",
    ]
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in files:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON list")
        for task in data:
            validate_task(path, task)
            if task["id"] in seen:
                raise ValueError(f"duplicate task id: {task['id']}")
            seen.add(task["id"])
            tasks.append(task)
    return tasks


def validate_task(path: Path, task: dict[str, Any]) -> None:
    for key in ("id", "category", "task"):
        if key not in task:
            raise ValueError(f"{path}: task missing required key '{key}'")
    if "expected_tools" not in task and "forbidden_tools" not in task:
        if task["category"] != "direct_reasoning":
            raise ValueError(f"{path}: {task['id']} needs expected_tools or forbidden_tools")


def filter_tasks(
    tasks: list[dict[str, Any]],
    category: str | None,
    task_id: str | None,
) -> list[dict[str, Any]]:
    if category:
        aliases = {
            "reasoning": "direct_reasoning",
            "direct": "direct_reasoning",
            "single": "single_tool",
            "tool": "single_tool",
            "multi": "multi_step",
            "recovery": "failure_recovery",
            "advanced": "advanced",
            "long": "advanced",
            "context": "advanced",
            "hallucination": "advanced",
        }
        category = aliases.get(category, category)
        tasks = [task for task in tasks if task["category"] == category]
    if task_id:
        tasks = [task for task in tasks if task["id"] == task_id]
    if not tasks:
        raise ValueError("no benchmark tasks matched the filter")
    return tasks


def build_provider(args) -> Any:
    if args.mode == "local":
        return create_provider("ollama", args.local_model)
    return create_provider(args.provider, args.model)


def run_one(task: dict[str, Any], provider: Any, quiet: bool, timeout_seconds: int = 300) -> dict[str, Any]:
    tracer = EvalTracer(task)
    start = time.perf_counter()
    answer = ""
    error = None

    try:
        timeout = int(math.ceil(float(task.get("timeout_seconds", timeout_seconds))))
        with time_limit(timeout):
            answer = run_agent(
                task=task["task"],
                provider=provider,
                verbose=not quiet,
                tool_dispatcher=tracer.dispatch,
            )
    except Exception as exc:
        error = str(exc)

    latency = round(time.perf_counter() - start, 3)
    result = {
        "id": task["id"],
        "category": task["category"],
        "task": task["task"],
        "final_answer": answer,
        "tool_calls": tracer.to_dicts(),
        "tool_names": tracer.tool_names(),
        "latency_seconds": latency,
        "retry_count": tracer.retry_count(),
        "estimated_cost_usd": None,
        "error": error,
    }
    grade = grade_task(task, result)
    result["passed"] = grade.passed
    result["checks"] = grade.checks
    result["failure_reasons"] = grade.failure_reasons
    result["slo_checks"] = grade.slo_checks
    result["slo_failure_reasons"] = grade.slo_failure_reasons
    return result


@contextmanager
def time_limit(seconds: int):
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _raise_timeout(_signum, _frame):
        raise TimeoutError(f"task timed out after {seconds}s")

    old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def write_outputs(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    HISTORY_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    history_row = {
        "run_started_at": payload["run_started_at"],
        "mode": payload["mode"],
        "model": payload["model"],
        "summary": payload["summary"],
    }
    with HISTORY_OUTPUT.open("a") as f:
        f.write(json.dumps(history_row) + "\n")


def print_report(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    print("\nMini Agent Eval Summary")
    print("=======================")
    print(f"Model: {payload['model']}")
    print(f"Tasks: {summary['passed_tasks']}/{summary['total_tasks']} passed")
    print(f"Task completion: {summary['task_completion_rate']}%")
    print(f"Tool selection: {summary['tool_selection_accuracy']}%")
    print(f"Multi-step completion: {summary['multi_step_completion_rate']}%")
    print(f"Recovery success: {summary['recovery_success_rate']}%")
    print(f"Advanced success: {summary['advanced_success_rate']}%")
    print(f"Avg latency: {summary['avg_latency_seconds']}s")
    print(f"Latency SLO pass rate: {summary['latency_slo_pass_rate']}%")
    print(f"Avg tool calls: {summary['avg_tool_calls']}")

    failed = [result for result in payload["results"] if not result["passed"]]
    if failed:
        print("\nFailures")
        print("--------")
        for result in failed:
            reasons = "; ".join(result["failure_reasons"])
            print(f"- {result['id']}: {reasons}")

    slo_misses = [result for result in payload["results"] if result.get("slo_failure_reasons")]
    if slo_misses:
        print("\nSLO Misses")
        print("----------")
        for result in slo_misses:
            reasons = "; ".join(result["slo_failure_reasons"])
            print(f"- {result['id']}: {reasons}")


if __name__ == "__main__":
    main()
