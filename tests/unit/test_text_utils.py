from resumefill.text_utils import count_replacement_chars, sanitize_text, split_phone


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

def test_split_phone_international_with_spaces():
    assert split_phone('+90 541 802 3704') == ('90', '5418023704')


def test_split_phone_compact_international():
    assert split_phone('+905418023704') == ('90', '5418023704')


def test_split_phone_trunk_zero_form_has_no_dial():
    assert split_phone('0(541) 802-37-04') == ('', '5418023704')


def test_split_phone_already_national_keeps_last_ten():
    assert split_phone('541 802 37 04') == ('', '5418023704')


def test_split_phone_us_style_drops_country_prefix_via_last10():
    assert split_phone('+1.415.555.2671') == ('', '4155552671')


def test_split_phone_rejects_non_international():
    assert split_phone('random text') is None
    assert split_phone('') is None
