from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import DecisionEvent


class DecisionRecorder:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, stage: str, url: str, event: str, details: dict[str, Any] | None = None, level: str = "info") -> None:
        if self.path is None:
            return
        payload = DecisionEvent(stage=stage, url=url, event=event, details=details or {}, level=level)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(payload.model_dump_json())
            handle.write("\n")

    def record_escalation(
        self,
        *,
        url: str,
        previous_mode: str,
        trigger_condition: str,
        observed_signals: list[str],
        next_mode: str,
        final_outcome: str | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "previous_extraction_mode": previous_mode,
            "trigger_condition": trigger_condition,
            "observed_signals": observed_signals,
            "next_extraction_mode": next_mode,
        }
        if final_outcome:
            details["final_outcome"] = final_outcome
        self.record("escalation", url, "mode_change", details)
