"""Source-integrity guards.

These tests exist because of a real incident: a PowerShell
``Get-Content | Set-Content`` round-trip re-encoded ``ui/app.py`` from
UTF-8 through cp1252, silently replacing every emoji/Turkish character
with U+FFFD. Strings stay valid Python, so lint/tests passed while the UI
showed mojibake. These checks make that class of damage fail loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "resumefill"

# Files whose user-visible labels contain non-ASCII by design.
_EMOJI_MARKERS = {
    "ui/app.py": ["🚀", "⚙️", "👤", "🎯", "📈"],
}


def _iter_sources():
    yield from SRC.rglob("*.py")


def test_all_sources_are_valid_utf8_without_replacement_chars():
    for path in _iter_sources():
        raw = path.read_bytes()
        text = raw.decode("utf-8")  # hard failure on broken encoding
        assert "\ufffd" not in text, (
            f"{path.name} contains U+FFFD replacement characters — "
            "the file was re-encoded through a lossy codepage"
        )


def test_no_utf8_double_encoding_mojibake_signatures():
    # 'Ã' + 'â€' sequences are the fingerprint of UTF-8 bytes decoded as cp1252.
    signatures = ("Ã", "â€", "âš", "ðŸ")
    for path in _iter_sources():
        text = path.read_text(encoding="utf-8")
        for sig in signatures:
            assert sig not in text, f"{path.name} contains mojibake signature {sig!r}"


@pytest.mark.parametrize(
    ("rel", "markers"),
    sorted(_EMOJI_MARKERS.items()),
)
def test_ui_labels_keep_their_emoji(rel, markers):
    text = (SRC / rel).read_text(encoding="utf-8")
    for marker in markers:
        assert marker in text, f"{rel} lost the {marker!r} marker"
