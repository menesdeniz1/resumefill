"""
Agent Logger — Persistent JSONL logging for every agent run.

Creates a timestamped log file per run in a `logs/` directory.
Each line is a self-contained JSON object for easy parsing and debugging.
"""

import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse


class AgentLogger:
    """
    Logs every step, event, and error to a JSONL file.

    Usage:
        logger = AgentLogger(url="https://example.com/apply", model_id="gemini-2.5-flash")
        logger.log_step(step_num=1, output=agent_output, page_url="...")
        logger.log_event("model_switch", {"from": "flash", "to": "pro"})
        summary = logger.summary()
    """

    def __init__(self, url: str, model_id: str, fallback_model_id: str | None = None):
        self._start_time = time.time()
        self._url = url
        self._model_id = model_id
        self._fallback_model_id = fallback_model_id

        # Tracking counters
        self._step_count = 0
        self._error_count = 0
        self._pages_visited: list[str] = []
        self._actions_taken: list[str] = []

        # Create logs directory
        log_dir = os.path.expanduser(os.environ.get("RESUMEFILL_LOG_DIR", "~/.local/share/resumefill/logs"))
        os.makedirs(log_dir, exist_ok=True)

        # Build filename: run_2026-02-23_180300_example-com.jsonl
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        domain = urlparse(url).netloc.replace(".", "-") or "local"
        self._filepath = os.path.join(log_dir, f"run_{ts}_{domain}.jsonl")

        # Write header event
        self.log_event("run_start", {
            "url": url,
            "primary_model": model_id,
            "fallback_model": fallback_model_id,
        })

    @property
    def filepath(self) -> str:
        return self._filepath

    def _write(self, record: dict):
        """Append a single JSON line to the log file."""
        record["timestamp"] = datetime.now(timezone.utc).isoformat()
        with open(self._filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def log_step(self, step_num: int, output, page_url: str = ""):
        """
        Log a full agent step with all available data.

        Args:
            step_num: Step number from browser-use.
            output: AgentOutput from browser-use (has thinking, memory, next_goal, action, etc.)
            page_url: Current page URL from browser state.
        """
        self._step_count = step_num

        # Track page transitions
        if page_url and (not self._pages_visited or self._pages_visited[-1] != page_url):
            self._pages_visited.append(page_url)

        # Extract action names
        actions = []
        if hasattr(output, "action") and output.action:
            for act in output.action:
                try:
                    act_dict = act.model_dump(exclude_unset=True) if hasattr(act, "model_dump") else {}
                    for action_name in act_dict:
                        if act_dict[action_name] is not None:
                            actions.append(action_name)
                            self._actions_taken.append(action_name)
                except Exception:
                    actions.append("unknown")

        record = {
            "type": "step",
            "step": step_num,
            "page_url": page_url,
            "thinking": getattr(output, "thinking", None),
            "evaluation": getattr(output, "evaluation_previous_goal", None),
            "memory": getattr(output, "memory", None),
            "next_goal": getattr(output, "next_goal", None),
            "actions": actions,
        }
        self._write(record)

    def log_event(self, event_type: str, data: dict | None = None):
        """
        Log a named event (model switch, quota error, verification, etc.)

        Args:
            event_type: Short identifier (e.g., "model_switch", "quota_error", "cv_analysis")
            data: Arbitrary event data.
        """
        record = {
            "type": "event",
            "event": event_type,
        }
        if data:
            record["data"] = data

        if "error" in event_type:
            self._error_count += 1

        self._write(record)

    def log_error(self, error_msg: str, context: str = ""):
        """Shorthand for logging errors."""
        self._error_count += 1
        self._write({
            "type": "error",
            "message": error_msg,
            "context": context,
        })

    def log_verification(self, page_url: str, passed: bool, issues: list[str] | None = None):
        """Log a page verification result."""
        self._write({
            "type": "verification",
            "page_url": page_url,
            "passed": passed,
            "issues": issues or [],
        })

    def summary(self) -> dict:
        """Return a summary of the entire run."""
        elapsed = time.time() - self._start_time
        summary = {
            "total_steps": self._step_count,
            "total_errors": self._error_count,
            "pages_visited": len(self._pages_visited),
            "page_urls": self._pages_visited,
            "elapsed_seconds": round(elapsed, 1),
            "elapsed_human": f"{int(elapsed // 60)}m {int(elapsed % 60)}s",
            "log_file": self._filepath,
        }
        # Write summary as final event
        self.log_event("run_complete", summary)
        return summary
