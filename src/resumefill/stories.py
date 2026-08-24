"""STAR interview-story bank.

Users write their behavioural stories once (``data/stories.yml``); the dry-
run answer pack grounds its drafts in relevant specifics instead of
inventing generic achievements. Selection is plain token overlap ??? no
embeddings (YAGNI for a single-user tool).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from resumefill.text_utils import sanitize_text

_TOP_K = 2
_MIN_WORD_LENGTH = 3

_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "you", "our", "are",
        "have", "has", "will", "from", "they", "their", "them", "was",
        "were", "been", "being", "who", "whom", "which", "what", "when",
        "where", "how", "all", "any", "can", "not", "but", "its", "it's",
        "job", "role", "work", "team", "teams", "experience", "years",
    }
)


@dataclass(frozen=True)
class Story:
    """One behavioural story in STAR+Reflection form."""

    title: str
    tags: list[str] = field(default_factory=list)
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    reflection: str = ""

    def _search_text(self) -> str:
        return sanitize_text(" ".join([self.title, self.result, *self.tags])).lower()


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z????????????????????????]+", text.lower())
    return {w for w in words if len(w) >= _MIN_WORD_LENGTH and w not in _STOPWORDS}


def load_stories(path: Path) -> list[Story]:
    """Load stories from YAML; missing file or syntax errors yield ``[]``."""
    if not path.is_file():
        return []
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 ??? user-editable file must never crash runs
        print(f"?????? Could not parse {path.name}: {exc}", file=sys.stderr)
        return []

    raw_stories = data.get("stories") if isinstance(data, dict) else None
    if not isinstance(raw_stories, list):
        return []

    stories: list[Story] = []
    for index, item in enumerate(raw_stories):
        try:
            if not isinstance(item, dict):
                raise TypeError("story entry is not a mapping")
            title = str(item.get("title", "")).strip()
            if not title:
                raise ValueError("story has no title")
            stories.append(
                Story(
                    title=title,
                    tags=[str(t).strip() for t in item.get("tags", []) if str(t).strip()],
                    situation=str(item.get("situation", "")).strip(),
                    task=str(item.get("task", "")).strip(),
                    action=str(item.get("action", "")).strip(),
                    result=str(item.get("result", "")).strip(),
                    reflection=str(item.get("reflection", "")).strip(),
                )
            )
        except (TypeError, ValueError) as exc:
            print(f"?????? Skipping invalid story #{index}: {exc}", file=sys.stderr)
    return stories


def select_relevant(stories: list[Story], jd_text: str, k: int = _TOP_K) -> list[Story]:
    """Top-k stories whose tokens overlap the JD; zero-overlap ones excluded."""
    jd_tokens = _tokenize(sanitize_text(jd_text))
    if not jd_tokens:
        return []
    scored = [
        (len(jd_tokens & _tokenize(story._search_text())), story)  # noqa: SLF001 ??? intra-module
        for story in stories
    ]
    relevant = [(score, s) for score, s in scored if score > 0]
    relevant.sort(key=lambda pair: pair[0], reverse=True)
    return [s for _, s in relevant[:k]]


def build_stories_section(stories: list[Story]) -> str:
    """Markdown block for the answer-pack prompt; empty string when none."""
    if not stories:
        return ""
    lines = ["", "**RELEVANT STAR STORIES (ground your answers in these specifics):**", ""]
    for story in stories:
        lines.append(f"### {story.title}")
        for label, value in (
            ("Situation", story.situation),
            ("Task", story.task),
            ("Action", story.action),
            ("Result", story.result),
            ("Reflection", story.reflection),
        ):
            if value:
                lines.append(f"- {label}: {value}")
        lines.append("")
    return "\n".join(lines)

