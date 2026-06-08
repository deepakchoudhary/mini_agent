from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from tools import call_tool


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result_preview: str
    duration_seconds: float
    error: str | None = None
    injected_failure: bool = False


class EvalLimitExceeded(RuntimeError):
    pass


class EvalTracer:
    def __init__(
        self,
        task: dict[str, Any],
        dispatcher: Callable[[str, dict], str] = call_tool,
    ) -> None:
        self.task = task
        self.dispatcher = dispatcher
        self.records: list[ToolCallRecord] = []
        self.max_tool_calls = task.get("max_tool_calls")
        self.fault_injection = task.get("fault_injection") or {}
        self._fault_counts: dict[str, int] = {}

    def dispatch(self, name: str, arguments: dict) -> str:
        if self.max_tool_calls is not None and len(self.records) >= int(self.max_tool_calls):
            self.records.append(
                ToolCallRecord(
                    name=name,
                    arguments=dict(arguments),
                    result_preview="",
                    duration_seconds=0.0,
                    error=f"max_tool_calls exceeded: {self.max_tool_calls}",
                )
            )
            raise EvalLimitExceeded(f"max_tool_calls exceeded: {self.max_tool_calls}")

        start = time.perf_counter()
        injected = False
        error: str | None = None

        try:
            injected_result = self._maybe_inject_failure(name)
            if injected_result is not None:
                injected = True
                result = injected_result
            else:
                result = self.dispatcher(name, arguments)
            return result
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            duration = time.perf_counter() - start
            result_preview = locals().get("result", "")
            self.records.append(
                ToolCallRecord(
                    name=name,
                    arguments=dict(arguments),
                    result_preview=str(result_preview)[:300],
                    duration_seconds=round(duration, 4),
                    error=error,
                    injected_failure=injected,
                )
            )

    def _maybe_inject_failure(self, name: str) -> str | None:
        tool = self.fault_injection.get("tool")
        mode = self.fault_injection.get("failure_mode")
        if tool != name or not mode:
            return None

        count = self._fault_counts.get(name, 0)
        self._fault_counts[name] = count + 1

        if mode == "return_error_once" and count == 0:
            return f"Error: injected transient failure for {name}"
        if mode == "return_error_always":
            return f"Error: injected persistent failure for {name}"
        if mode == "raise_once" and count == 0:
            raise RuntimeError(f"injected transient exception for {name}")
        return None

    def tool_names(self) -> list[str]:
        return [record.name for record in self.records]

    def retry_count(self) -> int:
        counts: dict[str, int] = {}
        retries = 0
        for record in self.records:
            counts[record.name] = counts.get(record.name, 0) + 1
            if counts[record.name] > 1:
                retries += 1
        return retries

    def to_dicts(self) -> list[dict[str, Any]]:
        return [asdict(record) for record in self.records]
