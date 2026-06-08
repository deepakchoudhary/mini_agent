from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Grade:
    passed: bool
    checks: dict[str, bool]
    failure_reasons: list[str]
    slo_checks: dict[str, bool]
    slo_failure_reasons: list[str]


def grade_task(task: dict[str, Any], result: dict[str, Any]) -> Grade:
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    slo_checks: dict[str, bool] = {}
    slo_reasons: list[str] = []

    answer = (result.get("final_answer") or "").lower()
    tool_names = result.get("tool_names") or []

    _check_expected_tools(task, tool_names, checks, reasons)
    _check_forbidden_tools(task, tool_names, checks, reasons)
    _check_required_order(task, tool_names, checks, reasons)
    _check_answer_contains(task, answer, checks, reasons)
    _check_answer_contains_any(task, answer, checks, reasons)
    _check_answer_regex(task, result.get("final_answer") or "", checks, reasons)
    _check_tool_call_limit(task, tool_names, checks, reasons)
    _check_latency_slo(task, result, slo_checks, slo_reasons)
    _check_recovery(task, result, checks, reasons)

    if result.get("error"):
        checks["no_runtime_error"] = False
        reasons.append(f"runtime error: {result['error']}")
    else:
        checks["no_runtime_error"] = True

    return Grade(
        passed=all(checks.values()) if checks else True,
        checks=checks,
        failure_reasons=reasons,
        slo_checks=slo_checks,
        slo_failure_reasons=slo_reasons,
    )


def _check_expected_tools(task: dict[str, Any], tool_names: list[str], checks: dict[str, bool], reasons: list[str]) -> None:
    expected = task.get("expected_tools")
    if expected is None:
        return
    missing = [name for name in expected if name not in tool_names]
    checks["expected_tools"] = not missing
    if missing:
        reasons.append(f"missing expected tools: {missing}")


def _check_forbidden_tools(task: dict[str, Any], tool_names: list[str], checks: dict[str, bool], reasons: list[str]) -> None:
    forbidden = task.get("forbidden_tools")
    if forbidden is None:
        return
    used = [name for name in tool_names if name in forbidden]
    checks["forbidden_tools"] = not used
    if used:
        reasons.append(f"used forbidden tools: {used}")


def _check_required_order(task: dict[str, Any], tool_names: list[str], checks: dict[str, bool], reasons: list[str]) -> None:
    required = task.get("required_tool_order")
    if required is None:
        return
    position = 0
    for name in tool_names:
        if position < len(required) and name == required[position]:
            position += 1
    passed = position == len(required)
    checks["required_tool_order"] = passed
    if not passed:
        reasons.append(f"required tool order not satisfied: {required}; got {tool_names}")


def _check_answer_contains(task: dict[str, Any], answer: str, checks: dict[str, bool], reasons: list[str]) -> None:
    expected = task.get("expected_answer_contains")
    if expected is None:
        return
    normalized_answer = _normalize_for_contains(answer)
    missing = [
        text for text in expected
        if _normalize_for_contains(text) not in normalized_answer
    ]
    checks["expected_answer_contains"] = not missing
    if missing:
        reasons.append(f"answer missing required text: {missing}")


def _check_answer_contains_any(task: dict[str, Any], answer: str, checks: dict[str, bool], reasons: list[str]) -> None:
    expected = task.get("expected_answer_contains_any")
    if expected is None:
        return
    normalized_answer = _normalize_for_contains(answer)
    passed = any(_normalize_for_contains(text) in normalized_answer for text in expected)
    checks["expected_answer_contains_any"] = passed
    if not passed:
        reasons.append(f"answer missing any of: {expected}")


def _check_answer_regex(task: dict[str, Any], answer: str, checks: dict[str, bool], reasons: list[str]) -> None:
    pattern = task.get("expected_answer_regex")
    if pattern is None:
        return
    passed = re.search(pattern, answer, flags=re.IGNORECASE | re.MULTILINE) is not None
    checks["expected_answer_regex"] = passed
    if not passed:
        reasons.append(f"answer did not match regex: {pattern}")


def _check_tool_call_limit(task: dict[str, Any], tool_names: list[str], checks: dict[str, bool], reasons: list[str]) -> None:
    max_tool_calls = task.get("max_tool_calls")
    if max_tool_calls is None:
        return
    passed = len(tool_names) <= int(max_tool_calls)
    checks["max_tool_calls"] = passed
    if not passed:
        reasons.append(f"tool calls exceeded limit: {len(tool_names)} > {max_tool_calls}")


def _check_latency_slo(task: dict[str, Any], result: dict[str, Any], checks: dict[str, bool], reasons: list[str]) -> None:
    max_latency = task.get("max_latency_seconds")
    if max_latency is None:
        return
    latency = result.get("latency_seconds")
    passed = latency is not None and latency <= float(max_latency)
    checks["max_latency_seconds"] = passed
    if not passed:
        reasons.append(f"latency exceeded limit: {latency} > {max_latency}")


def _check_recovery(task: dict[str, Any], result: dict[str, Any], checks: dict[str, bool], reasons: list[str]) -> None:
    expected_min = task.get("expected_retry_count_min")
    if expected_min is None:
        return
    retry_count = result.get("retry_count", 0)
    answer = (result.get("final_answer") or "").lower()
    transparent_failure = any(
        text in answer
        for text in ("error", "failed", "unable", "cannot", "can't", "unavailable")
    )
    passed = retry_count >= int(expected_min) or transparent_failure
    checks["recovery_attempt"] = passed
    if not passed:
        reasons.append(
            f"retry count below expected minimum and no transparent failure: {retry_count} < {expected_min}"
        )


def _normalize_for_contains(text: str) -> str:
    text = text.lower()
    return re.sub(r"(?<=\d),(?=\d)", "", text)
