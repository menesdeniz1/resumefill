"""Aggregation over JSONL run logs.

Reads ``logs/*.jsonl`` produced by :class:`AgentLogger` and computes the
numbers that matter: how many runs, how many succeeded, per-platform
breakdown, where errors pile up, and token/cost totals when
``calculate_cost`` was enabled. Pure functions over files — no state.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from resumefill.platforms import detect_platform

MAX_RECENT_RUNS = 20


@dataclass
class RunRecord:
    file: str
    url: str
    domain: str
    platform: str
    model: str
    started_at: str
    steps: int
    errors: int
    elapsed_seconds: float | None
    elapsed_human: str | None
    success: bool | None  # None = legacy log without a recorded outcome
    total_tokens: int | None = None
    total_cost: float | None = None

    def as_row(self) -> dict:
        if self.success is True:
            outcome = "✅"
        elif self.success is False:
            outcome = "❌"
        else:
            outcome = "❔"
        when = self.started_at[:19].replace("T", " ") or "?"
        cost_str = f"${self.total_cost:.4f}" if self.total_cost is not None else "—"
        tokens_str = str(self.total_tokens) if self.total_tokens is not None else "—"
        return {
            "When": when,
            "Platform": self.platform,
            "Outcome": outcome,
            "Steps": self.steps,
            "Errors": self.errors,
            "Duration": self.elapsed_human or "?",
            "Tokens": tokens_str,
            "Cost": cost_str,
            "Model": self.model,
            "Domain": self.domain,
        }


def _parse_run(path: Path) -> RunRecord | None:
    """Parse one run log.

    Returns ``None`` for unreadable files. Logs without a ``run_start``
    event or without a ``run_complete`` event are skipped: an attempt we
    cannot see the outcome of must not silently inflate either side of the
    success rate.
    """
    url = ""
    model = ""
    started_at = ""
    steps = 0
    errors = 0
    completed = False
    success: bool | None = None
    elapsed_seconds: float | None = None
    elapsed_human: str | None = None
    total_tokens: int | None = None
    total_cost: float | None = None

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = record.get("type")
                if kind == "event":
                    event = record.get("event", "")
                    data = record.get("data") or {}
                    if event == "run_start":
                        url = str(data.get("url", ""))
                        model = str(data.get("primary_model", ""))
                        started_at = str(record.get("timestamp", ""))
                    elif event == "run_complete":
                        completed = True
                        raw_success = data.get("success")
                        success = bool(raw_success) if isinstance(raw_success, bool) else None
                        steps = int(data.get("total_steps") or 0)
                        errors = int(data.get("total_errors") or 0)
                        if data.get("elapsed_seconds") is not None:
                            elapsed_seconds = float(data["elapsed_seconds"])
                        if data.get("elapsed_human") is not None:
                            elapsed_human = str(data["elapsed_human"])
                        usage = data.get("usage")
                        if isinstance(usage, dict):
                            if usage.get("total_tokens") is not None:
                                with contextlib.suppress(ValueError, TypeError):
                                    total_tokens = int(usage["total_tokens"])
                            if usage.get("total_cost") is not None:
                                with contextlib.suppress(ValueError, TypeError):
                                    total_cost = float(usage["total_cost"])
                    elif "error" in event:
                        errors += 1
                elif kind == "error":
                    errors += 1
                elif kind == "step":
                    step_num = record.get("step")
                    if isinstance(step_num, int):
                        steps = max(steps, step_num)
    except OSError:
        return None

    if not url or not completed:
        return None

    host = urlparse(url).netloc or "local"
    return RunRecord(
        file=path.name,
        url=url,
        domain=host,
        platform=detect_platform(url).value,
        model=model,
        started_at=started_at,
        steps=steps,
        errors=errors,
        elapsed_seconds=elapsed_seconds,
        elapsed_human=elapsed_human,
        success=success,
        total_tokens=total_tokens,
        total_cost=total_cost,
    )


def aggregate_runs(log_dir: Path) -> dict:
    """Aggregate every parseable ``*.jsonl`` run log under ``log_dir``."""
    records: list[RunRecord] = []
    skipped = 0
    if log_dir.is_dir():
        for path in sorted(log_dir.glob("*.jsonl")):
            record = _parse_run(path)
            if record is None:
                skipped += 1
            else:
                records.append(record)

    records.sort(key=lambda r: r.started_at, reverse=True)

    finished = [r for r in records if r.success is not None]
    successful = sum(1 for r in finished if r.success)

    by_platform: dict[str, dict[str, int]] = {}
    for r in records:
        bucket = by_platform.setdefault(r.platform, {"runs": 0, "successful": 0, "errors": 0})
        bucket["runs"] += 1
        bucket["errors"] += r.errors
        if r.success is True:
            bucket["successful"] += 1

    avg_steps = round(sum(r.steps for r in records) / len(records), 1) if records else None
    costs = [r.total_cost for r in records if r.total_cost is not None]
    tokens = [r.total_tokens for r in records if r.total_tokens is not None]

    return {
        "total_runs": len(records),
        "successful_runs": successful,
        "failed_runs": sum(1 for r in finished if r.success is False),
        "success_rate": round(successful / len(finished), 3) if finished else None,
        "avg_steps": avg_steps,
        "total_errors": sum(r.errors for r in records),
        "total_cost": round(sum(costs), 4) if costs else None,
        "total_tokens": sum(tokens) if tokens else None,
        "avg_cost": round(sum(costs) / len(costs), 4) if costs else None,
        "skipped_files": skipped,
        "by_platform": by_platform,
        "recent": records[:MAX_RECENT_RUNS],
    }
