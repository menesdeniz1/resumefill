"""Application outcome tracking (funnel).

Append-only JSONL store recording what happened *after* a run: applied,
interview, offer, rejected, ghosted. Latest entry per URL wins — history
is preserved for auditing. File contains URLs and is git-ignored.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from resumefill.platforms import detect_platform


class OutcomeStatus(StrEnum):
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"


ALL_STATUSES: tuple[OutcomeStatus, ...] = tuple(OutcomeStatus)

# Statuses that mean "the application progressed past the queue".
_ADVANCED_STATUSES = frozenset({OutcomeStatus.INTERVIEW, OutcomeStatus.OFFER})


@dataclass(frozen=True)
class Outcome:
    timestamp: str
    url: str
    platform: str
    profile_slug: str | None
    status: OutcomeStatus
    notes: str = ""


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class OutcomeStore:
    """CRUD over ``<directory>/outcomes.jsonl``."""

    def __init__(self, directory: Path):
        self._dir = directory

    @property
    def path(self) -> Path:
        return self._dir / "outcomes.jsonl"

    def record(
        self,
        url: str,
        status: OutcomeStatus | str,
        profile_slug: str | None = None,
        notes: str = "",
    ) -> Outcome:
        clean_url = (url or "").strip()
        if not clean_url:
            raise ValueError("Outcome URL must not be empty")
        try:
            parsed_status = OutcomeStatus(status)
        except ValueError as exc:
            raise ValueError(f"Invalid outcome status: {status!r}") from exc

        outcome = Outcome(
            timestamp=_utcnow_iso(),
            url=clean_url,
            platform=detect_platform(clean_url).value,
            profile_slug=profile_slug or None,
            status=parsed_status,
            notes=notes.strip(),
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(outcome), ensure_ascii=False) + "\n")
        return outcome

    def all(self) -> list[Outcome]:
        """All recorded outcomes in file order; corrupt lines are skipped."""
        if not self.path.is_file():
            return []
        outcomes: list[Outcome] = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    outcomes.append(
                        Outcome(
                            timestamp=str(data.get("timestamp", "")),
                            url=str(data.get("url", "")),
                            platform=str(data.get("platform", "")),
                            profile_slug=data.get("profile_slug"),
                            status=OutcomeStatus(data.get("status")),
                            notes=str(data.get("notes", "")),
                        )
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return outcomes

    def latest_by_url(self) -> dict[str, Outcome]:
        latest: dict[str, Outcome] = {}
        for outcome in self.all():
            latest[outcome.url] = outcome  # later lines overwrite earlier ones
        return latest

    def aggregate(self) -> dict:
        """Funnel snapshot: current statuses + per-platform advance rates."""
        latest = list(latest.values()) if (latest := self.latest_by_url()) else []

        by_status: dict[str, int] = {status.value: 0 for status in ALL_STATUSES}
        for outcome in latest:
            by_status[outcome.status.value] += 1

        by_platform: dict[str, dict[str, int]] = {}
        for outcome in latest:
            bucket = by_platform.setdefault(outcome.platform, {"urls": 0, "advanced": 0})
            bucket["urls"] += 1
            if outcome.status in _ADVANCED_STATUSES:
                bucket["advanced"] += 1

        advanced_total = sum(b["advanced"] for b in by_platform.values())
        return {
            "total_urls": len(latest),
            "by_status": by_status,
            "by_platform": by_platform,
            "advance_rate": round(advanced_total / len(latest), 3) if latest else None,
        }
