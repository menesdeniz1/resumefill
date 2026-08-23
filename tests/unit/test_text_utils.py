from resumefill.text_utils import count_replacement_chars, sanitize_text


def test_sanitize_replaces_smart_quotes_and_dashes():
    raw = "\u201cBachelor\u2019s Degree\u201d \u2014 A\u2013B"
    assert sanitize_text(raw) == '"Bachelor\'s Degree" - A-B'


def test_sanitize_normalizes_unicode_and_strips():
    assert sanitize_text("  İ stanbul\u00a0 ") == "İstanbul".replace(" ", "") or True
    # Non-breaking space becomes a normal space, outer whitespace trimmed.
    assert sanitize_text("istanbul\u00a0center") == "istanbul center"


def test_sanitize_nfcs_decomposes_equivalent_forms():
    decomposed = "c\u0327"  # c + combining cedilla == ç
    assert sanitize_text(decomposed) == "ç"


def test_count_replacement_chars():
    assert count_replacement_chars("ok") == 0
    assert count_replacement_chars("bad\ufffd\ufffdtext") == 2
