"""Text sanitization for CV content.

PDF text extraction frequently produces mojibake: smart quotes become
sequences like ``?Ts`` (seen in real run logs where the agent tried to select
a dropdown option named ``Bachelor?Ts Degree``) and unmappable glyphs become
U+FFFD replacement characters. Everything the LLM sees — CV text, extracted
names, answers — flows through :func:`sanitize_text` so downstream string
matching stays reliable.
"""

from __future__ import annotations

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
