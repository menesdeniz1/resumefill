"""Persistent CV profiles.

A profile is the unit of reuse: one CV variant → one analyzed profile
(structured analysis + persona + raw text). Profiles live as individual
JSON files under ``data/profiles/<slug>.json`` so they are trivially
inspectable, editable and versionable.

Schema evolution: files carry ``schema_version``; readers ignore unknown
keys and default missing ones, so older files stay loadable as the schema
grows.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_slug(name: str) -> str:
    """Filesystem-safe slug from a person's name (accent-stripped)."""
    normalized = unicodedata.normalize("NFKD", name or "")
    ascii_only = normalized.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "profile"


@dataclass
class CvProfile:
    """One reusable, analyzed CV variant."""

    name: str
    email: str = ""
    phone: str = ""
    title: str = ""
    analysis: dict = field(default_factory=dict)
    style_profile: str = ""
    # Full sanitized CV text is kept so runs can still stage an upload file.
    cv_text: str = ""
    source_cv_sha256: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict) -> CvProfile:
        # Unknown keys are ignored (forward compatibility), missing ones default.
        known = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class ProfileStore:
    """CRUD access to profile JSON files in a single directory."""

    def __init__(self, directory: Path):
        self._dir = directory

    @staticmethod
    def _slug_to_filename(slug: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            raise ValueError(f"Invalid profile slug: {slug!r}")
        return f"{slug}.json"

    def _path(self, slug: str) -> Path:
        return self._dir / self._slug_to_filename(slug)

    def _write_atomic(self, path: Path, payload: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(self._dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def list(self) -> list[tuple[str, CvProfile]]:
        """All valid profiles as ``(slug, profile)`` pairs, sorted by name.

        Corrupt files are skipped — a broken user-data file must never
        break listing.
        """
        if not self._dir.is_dir():
            return []
        profiles: list[tuple[str, CvProfile]] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                profiles.append((path.stem, CvProfile.from_dict(data)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        profiles.sort(key=lambda pair: pair[1].name.lower())
        return profiles

    def load(self, slug: str) -> CvProfile:
        path = self._path(slug)
        if not path.is_file():
            raise FileNotFoundError(f"Profile not found: {slug!r}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return CvProfile.from_dict(data)

    def save(self, profile: CvProfile, slug: str | None = None) -> tuple[CvProfile, str]:
        """Persist a profile; returns (stored_profile, slug).

        With ``slug=None`` a new slug is derived from the name and deduped
        with numeric suffixes. With an explicit slug the existing file is
        overwritten in place (its ``created_at`` is preserved).
        """
        if slug is not None:
            final_slug = slug
            existing_path = self._path(final_slug)
            created_at = (
                CvProfile.from_dict(json.loads(existing_path.read_text(encoding="utf-8"))).created_at
                if existing_path.is_file()
                else profile.created_at
            )
        else:
            base = make_slug(profile.name)
            taken = {p.stem for p in self._dir.glob("*.json")} if self._dir.is_dir() else set()
            final_slug, counter = base, 2
            while final_slug in taken:
                final_slug = f"{base}-{counter}"
                counter += 1
            created_at = profile.created_at

        stored = replace(profile)
        stored.created_at = created_at
        stored.updated_at = _utcnow_iso()
        self._write_atomic(self._path(final_slug), stored.to_dict())
        return stored, final_slug

    def update(
        self,
        slug: str,
        *,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        title: str | None = None,
    ) -> CvProfile:
        """Edit the key identity fields in place (filename stays stable)."""
        profile = self.load(slug)
        if name is not None:
            profile.name = name
        if email is not None:
            profile.email = email
        if phone is not None:
            profile.phone = phone
        if title is not None:
            profile.title = title
        stored, _ = self.save(profile, slug=slug)
        return stored

    def delete(self, slug: str) -> bool:
        """Remove a profile; True when something was deleted."""
        path = self._path(slug)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def build_from_analysis(
        self,
        analysis: dict,
        style_profile: str,
        cv_text: str,
        source_cv_sha256: str | None,
    ) -> CvProfile:
        """Create a profile from fresh analyzer output."""
        skills = analysis.get("skills", {}) or {}
        return CvProfile(
            name=str(analysis.get("name") or "Unknown"),
            email=str(analysis.get("email") or ""),
            phone=str(analysis.get("phone") or ""),
            title=str(analysis.get("title") or ""),
            analysis={
                **analysis,
                "skills": {
                    "technical": skills.get("technical", []),
                    "tools": skills.get("tools", []),
                    "soft": skills.get("soft", []),
                },
            },
            style_profile=style_profile,
            cv_text=cv_text,
            source_cv_sha256=source_cv_sha256,
        )
