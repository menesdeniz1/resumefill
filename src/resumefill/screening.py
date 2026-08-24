"""Zero-token job-posting legitimacy screening.

Pure rule-based heuristics over pasted JD text (+optional URL history).
No LLM calls, no network — this is decision support, never a blocker.
Inspired by career-ops "Block G" (posting-legitimacy assessment), kept
deliberately minimal: false positives must stay rare, so prefer ``warn``
over ``danger`` unless the scam signal is explicit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from resumefill.text_utils import sanitize_text

FlagLevel = Literal["info", "warn", "danger"]

_LEVEL_ORDER: dict[str, int] = {"danger": 0, "warn": 1, "info": 2}


@dataclass(frozen=True)
class Flag:
    """One screening finding."""

    level: FlagLevel
    code: str
    message: str


# ── text heuristics ──────────────────────────────────────────────────────────

_DANGER_REGEXES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "fee_request",
        re.compile(r"\b(?:training|registration|onboarding|background\s*check)\s+fee\b", re.I),
    ),
    ("fee_request", re.compile(r"\bpay\b[^\n.]{0,40}\b(?:kit|equipment)\b", re.I)),
    ("fee_request", re.compile(r"\bsend\s+(?:us\s+)?money\b", re.I)),
)

_CRYPTO_TOKENS = ("crypto", "bitcoin", "usdt")
_PAYMENT_TOKENS = ("salary", "payment", "paid", "pay")

_WARN_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("commission_only", ("commission only", "unlimited income", "be your own boss")),
    ("whatsapp_contact", ("whatsapp",)),
)

_APPLY_EMAIL_DOMAINS = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com")

_CORPORATE_SIGNALS = ("we are", "our team", "about us", "our company")

_MIN_LENGTH_FOR_CONTENT = 200
_MAX_LENGTH_WITHOUT_COMPANY_SIGNAL = 400

_EMAIL_RE = re.compile(r"[\w.+-]+@([\w.-]+)")


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[.!?\n]", text) if s.strip()]


def _text_flags(jd: str) -> list[Flag]:
    flags: list[Flag] = []

    for code, pattern in _DANGER_REGEXES:
        if pattern.search(jd):
            flags.append(
                Flag("danger", code, "Explicit payment/fee request detected in the posting.")
            )

    for sentence in _sentences(jd):
        low = sentence.lower()
        if any(t in low for t in _CRYPTO_TOKENS) and any(t in low for t in _PAYMENT_TOKENS):
            flags.append(
                Flag(
                    "danger",
                    "crypto_payment",
                    "Crypto asset mentioned together with payment/salary in one sentence.",
                )
            )
            break

    seen_codes: set[str] = set()
    for code, phrases in _WARN_PHRASES:
        if code in seen_codes:
            continue
        if any(p in jd.lower() for p in phrases):
            seen_codes.add(code)
            flags.append(Flag("warn", code, f"Suspicious phrase matched: {code.replace('_', ' ')}."))

    for domain_match in _EMAIL_RE.finditer(jd):
        if domain_match.group(1).lower() in _APPLY_EMAIL_DOMAINS:
            flags.append(
                Flag(
                    "warn",
                    "personal_apply_email",
                    f"Applications directed to a personal e-mail domain ({domain_match.group(0)}).",
                )
            )
            break

    if len(jd) < _MIN_LENGTH_FOR_CONTENT:
        flags.append(Flag("info", "too_short", "Posting text is unusually short."))
    elif len(jd) <= _MAX_LENGTH_WITHOUT_COMPANY_SIGNAL and not any(
        s in jd.lower() for s in _CORPORATE_SIGNALS
    ):
        flags.append(
            Flag("info", "no_company_signal", "No company-description language found.")
        )

    return flags


# ── URL heuristics ───────────────────────────────────────────────────────────

_SHORTENER_DOMAINS = frozenset(
    {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly"}
)


def normalize_url(url: str) -> str:
    """Canonical form used for repost comparison (scheme/query stripped)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        host = (parts.netloc or "").lower().removeprefix("www.")
        path = parts.path.rstrip("/").lower()
        return f"{host}{path}"
    except ValueError:
        return raw.lower()


def _url_flags(url: str | None, history_urls: set[str] | None) -> list[Flag]:
    if not url:
        return []
    flags: list[Flag] = []
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host in _SHORTENER_DOMAINS:
        flags.append(Flag("info", "shortened_url", "Posting link uses a URL shortener."))
    if history_urls:
        canonical = normalize_url(url)
        if canonical and any(normalize_url(u) == canonical for u in history_urls):
            flags.append(
                Flag(
                    "warn",
                    "repost",
                    "This exact posting was processed before — possible repost/ghost job.",
                )
            )
    return flags


# ── entry point ──────────────────────────────────────────────────────────────


def screen_jd(
    jd_text: str,
    url: str | None = None,
    history_urls: set[str] | None = None,
) -> list[Flag]:
    """Screen a pasted job description; returns flags sorted by severity."""
    jd = sanitize_text(jd_text)
    flags: list[Flag] = []
    if jd:
        flags.extend(_text_flags(jd))
    flags.extend(_url_flags(url, history_urls))

    # De-duplicate identical codes (the regex table can emit the same code
    # twice), keeping the first occurrence (dangers were added first).
    deduped: dict[str, Flag] = {}
    for flag in flags:
        deduped.setdefault(flag.code, flag)

    return sorted(deduped.values(), key=lambda f: _LEVEL_ORDER[f.level])
