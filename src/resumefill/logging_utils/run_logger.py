"""Persistent JSONL logging for every agent run.

Creates a timestamped log file per run in the configured logs directory.
Each line is a self-contained JSON object for easy parsing and debugging.
Log files contain personal data and are git-ignored by design.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse


def _domain_slug(url: str) -> str:
    host = urlparse(url).netloc or "local"
    return re.sub(r"[^a-zA-Z0-9-]+", "-", host).strip("-") or "local"


class AgentLogger:
    """Logs every step, event, and error to a JSONL file."""

    def __init__(self, url: str, model_id: str, fallback_model_id: str | None, log_dir: Path):
        self._start_time = time.time()
        self._url = url
        self._model_id = model_id
        self._fallback_model_id = fallback_model_id

        self._step_count = 0
        self._error_count = 0
        self._pages_visited: list[str] = []
        self._actions_taken: list[str] = []

        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self._filepath = log_dir / f"run_{ts}_{_domain_slug(url)}.jsonl"

        self.log_event(
            "run_start",
            {
                "url": url,
                "primary_model": model_id,
                "fallback_model": fallback_model_id,
            },
        )

    @property
    def filepath(self) -> Path:
        return self._filepath

    def _write(self, record: dict) -> None:
        record["timestamp"] = datetime.now(UTC).isoformat()
        with open(self._filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def log_step(self, step_num: int, output, page_url: str = "") -> None:
        """Log a full agent step with all available data."""
        self._step_count = step_num

        if page_url and (not self._pages_visited or self._pages_visited[-1] != page_url):
            self._pages_visited.append(page_url)

        actions: list[str] = []
        raw_actions = getattr(output, "action", None)
        if raw_actions:
            for act in raw_actions:
                try:
                    dump = act.model_dump(exclude_unset=True) if hasattr(act, "model_dump") else {}
                    for name, value in dump.items():
                        if value is not None:
                            actions.append(name)
                            self._actions_taken.append(name)
                except Exception:  # noqa: BLE001 — logging must never break the agent
                    actions.append("unknown")

        self._write(
            {
                "type": "step",
                "step": step_num,
                "page_url": page_url,
                "thinking": getattr(output, "thinking", None),
                "evaluation": getattr(output, "evaluation_previous_goal", None),
                "memory": getattr(output, "memory", None),
                "next_goal": getattr(output, "next_goal", None),
                "actions": actions,
            }
        )

    def log_event(self, event_type: str, data: dict | None = None) -> None:
        """Log a named event (model switch, quota error, verification...)."""
        record: dict = {"type": "event", "event": event_type}
        if data:
            record["data"] = data
        if "error" in event_type:
            self._error_count += 1
        self._write(record)

    def log_error(self, error_msg: str, context: str = "") -> None:
        """Shorthand for logging errors."""
        self._error_count += 1
        self._write({"type": "error", "message": error_msg, "context": context})

    def summary(self) -> dict:
        """Return (and persist) a summary of the entire run."""
        elapsed = time.time() - self._start_time
        summary = {
            "total_steps": self._step_count,
            "total_errors": self._error_count,
            "pages_visited": len(self._pages_visited),
            "page_urls": self._pages_visited,
            "elapsed_seconds": round(elapsed, 1),
            "elapsed_human": f"{int(elapsed // 60)}m {int(elapsed % 60)}s",
            "log_file": str(self._filepath),
        }
        self.log_event("run_complete", summary)
        return summary
