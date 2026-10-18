"""Persistent answer memory (PLAN_P5).

Every question the applicant answers in a real form can be harvested into
``data/answers.yml`` (git-ignored, PII). Approved entries ride along on
later applications as pre-approved answers so the agent reuses verified
wording instead of re-inventing it. Matching is normalized exact first,
then ``difflib`` ratio — no embeddings (single-user tool, YAGNI).
"""

from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

_MATCH_THRESHOLD = 0.85


def normalize_question(question: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    lowered = question.lower()
    no_punct = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", no_punct).strip()


@dataclass
class MemoryEntry:
    """One question the user has answered once and may answer again."""

    question: str
    answer: str
    source: str = "manual"  # harvest | manual
    approved: bool = False
    times_used: int = 0
    last_used: str | None = None


class MemoryStore:
    """YAML-backed question/answer bank under ``data/answers.yml``."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "answers.yml"

    # --- persistence ---------------------------------------------------------

    def _load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            import yaml

            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — user-editable file must never crash runs
            print(f"[WARN] Could not parse {self.path.name}: {exc}", file=sys.stderr)
            return []
        raw = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def _save(self, entries: list[MemoryEntry]) -> None:
        import yaml

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"answers": [asdict(entry) for entry in entries]}
        self.path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    # --- reads ---------------------------------------------------------------

    def entries(self, only_approved: bool = False) -> list[MemoryEntry]:
        """All valid entries; malformed raw rows are skipped silently."""
        result: list[MemoryEntry] = []
        for raw in self._load():
            question = str(raw.get("question", "")).strip()
            answer = str(raw.get("answer", "")).strip()
            if not question or not answer:
                continue
            last_used = raw.get("last_used")
            if isinstance(last_used, str) and last_used.strip() in {"", "None", "null"}:
                last_used = None
            elif last_used is not None and not isinstance(last_used, str):
                last_used = str(last_used)
            result.append(
                MemoryEntry(
                    question=question,
                    answer=answer,
                    source=str(raw.get("source", "manual")) or "manual",
                    approved=bool(raw.get("approved", False)),
                    times_used=int(raw.get("times_used", 0) or 0),
                    last_used=last_used,
                )
            )
        if only_approved:
            result = [entry for entry in result if entry.approved]
        return result

    def find(self, question: str) -> MemoryEntry | None:
        """Best matching entry: normalized exact first, then ratio >= 0.85."""
        entries = self.entries()
        if not entries:
            return None
        target = normalize_question(question)
        for entry in entries:
            if normalize_question(entry.question) == target:
                return entry
        best, best_ratio = None, _MATCH_THRESHOLD
        for entry in entries:
            ratio = SequenceMatcher(None, target, normalize_question(entry.question)).ratio()
            if ratio > best_ratio:
                best, best_ratio = entry, ratio
        return best

    # --- mutations -----------------------------------------------------------

    def add_or_update(
        self,
        question: str,
        answer: str,
        *,
        source: str = "manual",
        approved: bool = False,
    ) -> tuple[MemoryEntry, bool]:
        """Insert (False) or overwrite in place (True), keyed by question."""
        entries = self.entries()
        question, answer = question.strip(), answer.strip()
        target = normalize_question(question)
        for index, entry in enumerate(entries):
            if normalize_question(entry.question) == target:
                entries[index] = MemoryEntry(
                    question=question if question else entry.question,
                    answer=answer if answer else entry.answer,
                    source=source,
                    approved=approved,
                    times_used=entry.times_used,
                    last_used=entry.last_used,
                )
                self._save(entries)
                return entries[index], True
        fresh = MemoryEntry(question=question, answer=answer, source=source, approved=approved)
        entries.append(fresh)
        self._save(entries)
        return fresh, False

    def approve(self, question: str) -> bool:
        return self._patch(self.find(question), approved=True)

    def delete(self, question: str) -> bool:
        entry = self.find(question)
        if entry is None:
            return False
        target = normalize_question(entry.question)
        remaining = [
            e for e in self.entries() if normalize_question(e.question) != target
        ]
        self._save(remaining)
        return True

    def mark_used(self, question: str) -> bool:
        entry = self.find(question)
        return self._patch(
            entry,
            times_used=(entry.times_used + 1) if entry else 0,
            last_used=datetime.now(UTC).date().isoformat(),
        )

    # --- internals -----------------------------------------------------------

    def _patch(self, entry: MemoryEntry | None, **changes) -> bool:
        """Identity-based matching is unreliable across ``entries()`` calls
        since the list is rebuilt from YAML; match on normalized question."""
        if entry is None:
            return False
        target = normalize_question(entry.question)
        updated: list[MemoryEntry] = []
        for e in self.entries():
            if normalize_question(e.question) == target:
                updated.append(
                    MemoryEntry(
                        question=entry.question,
                        answer=entry.answer,
                        source=entry.source,
                        approved=changes.get("approved", entry.approved),
                        times_used=changes.get("times_used", entry.times_used),
                        last_used=changes.get("last_used", entry.last_used),
                    )
                )
            else:
                updated.append(e)
        self._save(updated)
        return True
