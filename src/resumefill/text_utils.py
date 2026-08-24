"""Text sanitization for CV content.

PDF text extraction frequently produces mojibake: smart quotes become
sequences like ``?Ts`` (seen in real run logs where the agent tried to select
a dropdown option named ``Bachelor?Ts Degree``) and unmappable glyphs become
U+FFFD replacement characters. Everything the LLM sees — CV text, extracted
names, answers — flows through :func:`sanitize_text` so downstream string
matching stays reliable.
"""

from __future__ import annotations

import re
import unicodedata

# Characters that commonly get mangled by PDF codecs / Windows codepages,
# mapped to their safe ASCII equivalents.
_REPLACEMENTS = {
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote
    "\u201a": ",",  # single low quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",  # non-breaking space
    "\u2022": "*",  # bullet
}

REPLACEMENT_CHAR = "\ufffd"


def sanitize_text(text: str) -> str:
    """Normalize unicode, replace problematic characters, and trim."""
    normalized = unicodedata.normalize("NFC", text)
    for src, dst in _REPLACEMENTS.items():
        normalized = normalized.replace(src, dst)
    return normalized.strip()


def count_replacement_chars(text: str) -> int:
    """Count U+FFFD characters — a reliable signal of lossy extraction."""
    return text.count(REPLACEMENT_CHAR)


_PHONE_DIGITS_RE = re.compile(r"\D+")


def split_phone(full: str) -> tuple[str, str] | None:
    """Split a phone into ``(dial_code, national_number)``.

    Honest contract (no country-table guessing):
    - ``+90 …`` / ``0090…`` with 12 digits  -> ``("90", "5XXXXXXXXX")``
    - trunk-zero form ``0532…`` (11 digits) -> ``("",   "532…")``
    - anything ≥10 digits                   -> ``("", last-10-digits)``
    - otherwise ``None`` (not parseable)
    """
    raw = sanitize_text(full)
    if not raw:
        return None
    digits = _PHONE_DIGITS_RE.sub("", raw)
    if not digits:
        return None

    international = raw.lstrip().startswith("+") or digits.startswith("00")
    if digits.startswith("00"):
        digits = digits[2:]

    if international and digits.startswith("90") and len(digits) == 12:
        return "90", digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        return "", digits[1:]
    if len(digits) >= 10:
        return "", digits[-10:]
    return None
