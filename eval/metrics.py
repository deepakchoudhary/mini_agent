from __future__ import annotations

from collections import defaultdict
from typing import Any


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_category[result["category"]].append(result)

    tool_calls = [len(result["tool_names"]) for result in results]
    latencies = [result["latency_seconds"] for result in results if result["latency_seconds"] is not None]
    latency_slo_results = [
        result["slo_checks"]["max_latency_seconds"]
        for result in results
        if "max_latency_seconds" in result.get("slo_checks", {})
    ]
    tool_errors = sum(
        1
        for result in results
        for call in result["tool_calls"]
        if call.get("error") or str(call.get("result_preview", "")).lower().startswith("error:")
    )
    total_tool_calls = sum(tool_calls)

    return {
        "task_completion_rate": _pct(passed, total),
        "tool_selection_accuracy": _category_rate(by_category, ["single_tool"]),
        "multi_step_completion_rate": _category_rate(by_category, ["multi_step"]),
        "recovery_success_rate": _category_rate(by_category, ["failure_recovery"]),
        "advanced_success_rate": _category_rate(by_category, ["advanced"]),
        "tool_error_rate": _pct(tool_errors, total_tool_calls),
        "avg_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "latency_slo_pass_rate": _pct(
            sum(1 for passed_slo in latency_slo_results if passed_slo),
            len(latency_slo_results),
        ),
        "avg_tool_calls": round(sum(tool_calls) / total, 3) if total else None,
        "estimated_cost_usd": None,
        "total_tasks": total,
        "passed_tasks": passed,
        "failed_tasks": total - passed,
        "by_category": {
            category: {
                "total": len(items),
                "passed": sum(1 for item in items if item["passed"]),
                "pass_rate": _pct(sum(1 for item in items if item["passed"]), len(items)),
            }
            for category, items in sorted(by_category.items())
        },
    }


def _category_rate(by_category: dict[str, list[dict[str, Any]]], categories: list[str]) -> float | None:
    items = [item for category in categories for item in by_category.get(category, [])]
    if not items:
        return None
    return _pct(sum(1 for item in items if item["passed"]), len(items))


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round((numerator / denominator) * 100, 2)
