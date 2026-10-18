"""Auto-fetch job descriptions from public ATS sources (PLAN_P5-4).

Supported out of the box: Greenhouse and Lever postings, both of which
also expose a plain HTTP JSON API, plus a generic HTML fallback for any
board that ships its copy server-side. JavaScript-heavy boards (Workday,
SuccessFactors, LinkedIn, Glassdoor) are detected and refuse with an
action hint instead of guessing. Zero new dependencies: urllib only.
"""

from __future__ import annotations

import html as html_module
import json
import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

_TIMEOUT = 15.0
_MAX_BYTES = 400_000
_MAX_TEXT = 15_000
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_JS_HEAVY_HOSTS = (
    "myworkdayjobs.com",
    "workday",
    "successfactors",
    "linkedin.com",
    "glassdoor.com",
    "smartapply",
)


@dataclass
class JdFetch:
    """Result of one fetch attempt; empty ``text`` means failure."""

    title: str = ""
    text: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
        return bytes(response.read(_MAX_BYTES))


class _TextParser(HTMLParser):
    """Collects <title> plus the text of description-bearing containers."""

    _DESC_MARKERS = ("jobdescription", "job-description", "description", "content", "section-page")
    _SKIP = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._chunks: list[list[str]] = []
        self._active = -1
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in {"div", "section", "article"}:
            joined = " ".join(value or "" for _, value in attrs).lower()
            if any(marker in joined for marker in self._DESC_MARKERS):
                self._chunks.append([])
                self._active = len(self._chunks) - 1

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in {"div", "section", "article"}:
            self._active = -1

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
            return
        if self._active >= 0:
            self._chunks[self._active].append(text)

    def description_text(self, cap: int = _MAX_TEXT) -> str:
        """Longest matching container wins (meta descriptions are short)."""
        best = ""
        for chunks in self._chunks:
            joined = re.sub(r"\s+", " ", " ".join(chunks)).strip()
            if len(joined) > len(best):
                best = joined
        return best[:cap]


def _generic_html_parse(raw: bytes) -> JdFetch:
    decoded = raw.decode("utf-8", errors="replace")
    parser = _TextParser()
    parser.feed(decoded)
    description = parser.description_text()
    if not description:
        match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            decoded,
            re.IGNORECASE,
        )
        if match:
            description = re.sub(r"\s+", " ", match.group(1)).strip()[:_MAX_TEXT]
    return JdFetch(title=parser.title[:200], text=description)


def _greenhouse(url: str, http_get) -> JdFetch | None:
    parsed = urlparse(url)
    segments = [seg for seg in parsed.path.split("/") if seg]
    # boards.greenhouse.io / job-boards.greenhouse.io /<company>/jobs/<id>
    if "greenhouse.io" not in parsed.netloc.lower() or len(segments) != 3:
        return None
    company, marker, job_id = segments
    if marker != "jobs" or not job_id.isdigit():
        return None
    api = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"
    try:
        data = json.loads(http_get(api).decode("utf-8", errors="replace"))
    except (ValueError, OSError):  # private posting, rate limit, non-JSON → page fallback
        return None
    html_blob = html_module.unescape(str(data.get("content", "")))  # API serves escaped markup
    title = str(data.get("title", ""))[:200]
    if not html_blob:
        return JdFetch(title=title)
    parser = _TextParser()
    parser.feed(html_blob)
    text = parser.description_text() or re.sub(r"<[^>]+>", " ", html_blob)
    text = re.sub(r"\s+", " ", text).strip()[:_MAX_TEXT]
    if not text:
        return JdFetch(title=title)
    return JdFetch(title=title, text=text)


def _lever(url: str, http_get) -> JdFetch | None:
    parsed = urlparse(url)
    if "lever.co" not in parsed.netloc.lower():
        return None
    segments = [seg for seg in parsed.path.split("/") if seg]
    # jobs.lever.co/<company>/<id>
    if len(segments) != 2 or segments[1] == "new":
        return None
    api = f"https://api.lever.co/v0/postings/{segments[0]}/{segments[1]}?mode=json"
    try:
        data = json.loads(http_get(api).decode("utf-8", errors="replace"))
    except (ValueError, OSError):
        data = {}
    title = str(data.get("title", ""))[:200]
    text = re.sub(r"\s+", " ", str(data.get("descriptionPlain") or data.get("text") or "")).strip()
    if text:
        return JdFetch(title=title, text=text[:_MAX_TEXT])
    # JSON shape differs across postings; fall back to the rendered page.
    generic = _generic_html_parse(http_get(url))
    generic.title = generic.title or title
    return generic


def fetch_jd(url: str, *, http_get=_http_get) -> JdFetch:
    """Fetch title + description for an application URL.

    ``http_get`` is injectable so tests can feed recorded payloads without
    touching the network. Every failure degrades to a manual-paste hint.
    """
    host = urlparse(url).netloc.lower() or url.lower()
    if any(marker in host for marker in _JS_HEAVY_HOSTS):
        return JdFetch(reason="JavaScript-only board — paste the description manually.")
    try:
        if "lever.co" in host:
            fetched = _lever(url, http_get)
            if fetched is not None and fetched.ok:
                return fetched
        if "greenhouse.io" in host:
            fetched = _greenhouse(url, http_get)
            if fetched is not None and fetched.ok:
                return fetched
        parsed = _generic_html_parse(http_get(url))
        if parsed.ok:
            return parsed
        return JdFetch(
            reason=(
                f"Could not auto-extract a description from {host} — paste the "
                f"description manually. (page title: {parsed.title or 'n/a'})"
            )
        )
    except Exception as exc:  # noqa: BLE001 — every network/parse failure degrades gracefully
        return JdFetch(
            reason=f"Fetch failed ({exc.__class__.__name__}) — paste the description manually."
        )
