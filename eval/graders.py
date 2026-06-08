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
    _check_forbidden_answer_contains(task, answer, checks, reasons)
    _check_answer_regex(task, result.get("final_answer") or "", checks, reasons)
    _check_min_tool_calls(task, tool_names, checks, reasons)
    _check_tool_call_counts(task, tool_names, checks, reasons)
    _check_calculate_sequence(task, result, checks, reasons)
    _check_tool_argument_contains(task, result, checks, reasons)
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


def _check_forbidden_answer_contains(task: dict[str, Any], answer: str, checks: dict[str, bool], reasons: list[str]) -> None:
    forbidden = task.get("forbidden_answer_contains")
    if forbidden is None:
        return
    normalized_answer = _normalize_for_contains(answer)
    found = [
        text for text in forbidden
        if _normalize_for_contains(text) in normalized_answer
    ]
    checks["forbidden_answer_contains"] = not found
    if found:
        reasons.append(f"answer included forbidden text: {found}")


def _check_answer_regex(task: dict[str, Any], answer: str, checks: dict[str, bool], reasons: list[str]) -> None:
    pattern = task.get("expected_answer_regex")
    if pattern is None:
        return
    passed = re.search(pattern, answer, flags=re.IGNORECASE | re.MULTILINE) is not None
    checks["expected_answer_regex"] = passed
    if not passed:
        reasons.append(f"answer did not match regex: {pattern}")


def _check_tool_call_counts(task: dict[str, Any], tool_names: list[str], checks: dict[str, bool], reasons: list[str]) -> None:
    expected_counts = task.get("expected_tool_counts")
    if expected_counts is None:
        return
    actual = {name: tool_names.count(name) for name in set(tool_names)}
    mismatches = {
        name: {"expected": count, "actual": actual.get(name, 0)}
        for name, count in expected_counts.items()
        if actual.get(name, 0) != count
    }
    checks["expected_tool_counts"] = not mismatches
    if mismatches:
        reasons.append(f"tool call count mismatch: {mismatches}")


def _check_min_tool_calls(task: dict[str, Any], tool_names: list[str], checks: dict[str, bool], reasons: list[str]) -> None:
    minimum = task.get("expected_min_tool_calls")
    if minimum is None:
        return
    passed = len(tool_names) >= int(minimum)
    checks["expected_min_tool_calls"] = passed
    if not passed:
        reasons.append(f"tool calls below expected minimum: {len(tool_names)} < {minimum}")


def _check_calculate_sequence(task: dict[str, Any], result: dict[str, Any], checks: dict[str, bool], reasons: list[str]) -> None:
    expected = task.get("expected_calculate_sequence")
    if expected is None:
        return
    calls = [
        str((call.get("arguments") or {}).get("expression", ""))
        for call in result.get("tool_calls", [])
        if call.get("name") == "calculate"
    ]
    actual = [_normalize_expression(expression) for expression in calls]
    wanted = [_normalize_expression(expression) for expression in expected]
    position = 0
    for expression in actual:
        if position < len(wanted) and wanted[position] in expression:
            position += 1
    passed = position == len(wanted)
    checks["expected_calculate_sequence"] = passed
    if not passed:
        reasons.append(
            f"calculate sequence incomplete: matched {position}/{len(wanted)} expected expressions"
        )


def _check_tool_argument_contains(task: dict[str, Any], result: dict[str, Any], checks: dict[str, bool], reasons: list[str]) -> None:
    expected = task.get("expected_tool_argument_contains")
    if expected is None:
        return
    tool_calls = result.get("tool_calls", [])
    missing: list[dict[str, str]] = []
    for item in expected:
        tool = item["tool"]
        field = item["field"]
        text = _normalize_for_contains(str(item["contains"]))
        matched = False
        for call in tool_calls:
            if call.get("name") != tool:
                continue
            value = _normalize_for_contains(str((call.get("arguments") or {}).get(field, "")))
            if text in value:
                matched = True
                break
        if not matched:
            missing.append(item)
    checks["expected_tool_argument_contains"] = not missing
    if missing:
        reasons.append(f"missing expected tool argument content: {missing}")


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


def _normalize_expression(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())
