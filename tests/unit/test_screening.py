"""Screening heuristics: pure functions, zero network, zero LLM."""

from resumefill.screening import Flag, normalize_url, screen_jd


def _codes(flags: list[Flag]) -> set[str]:
    return {f.code for f in flags}


# ── normalize_url ────────────────────────────────────────────────────────────

def test_normalize_url_strips_scheme_query_www_and_trailing_slash():
    assert normalize_url("https://jobs.lever.co/acme/123?utm_source=x") == "jobs.lever.co/acme/123"
    assert normalize_url("http://www.lever.co/acme/123/") == "lever.co/acme/123"
    assert (
        normalize_url("HTTPS://JOBS.EXAMPLE.COM/Role/")
        == "jobs.example.com/role"
    )


def test_normalize_url_handles_garbage_and_empty():
    assert normalize_url("") == ""
    assert normalize_url(None or "") == ""
    assert isinstance(normalize_url("not a url"), str)


# ── danger flags ─────────────────────────────────────────────────────────────

def test_fee_request_detected():
    jd = "We offer great training! Candidates must pay a training fee of $200."
    flags = screen_jd(jd)
    assert "fee_request" in _codes(flags)
    assert any(f.level == "danger" for f in flags)


def test_send_money_detected():
    flags = screen_jd("Please send money for the onboarding package.")
    assert "fee_request" in _codes(flags)


def test_crypto_plus_payment_in_same_sentence():
    flags = screen_jd("Salary is paid in USDT crypto for flexibility.")
    assert "crypto_payment" in _codes(flags)


def test_crypto_alone_is_not_flagged():
    codes = _codes(screen_jd("Experience with crypto trading platforms is a plus. Salary is competitive."))
    assert "crypto_payment" not in codes


# ── warn flags ───────────────────────────────────────────────────────────────

def test_commission_only_warn():
    flags = screen_jd("Unlimited income potential! Be your own boss today.")
    assert "commission_only" in _codes(flags)


def test_personal_apply_email_warn():
    jd = "Send your CV to hr.freelance.hiring@gmail.com with subject APPLY."
    flags = screen_jd(jd)
    codes = _codes(flags)
    assert "personal_apply_email" in codes
    assert all(f.level != "danger" for f in flags)


def test_corporate_email_not_flagged():
    assert "personal_apply_email" not in _codes(
        screen_jd("Apply via careers@acme-corp.com. We are a growing fintech team.")
    )


# ── info flags ───────────────────────────────────────────────────────────────

def test_too_short_info():
    flags = screen_jd("Hiring devs. DM us.")
    assert "too_short" in _codes(flags)


def test_no_company_signal_on_medium_length_posting():
    jd = ("Join an exciting opportunity to work on cutting edge projects " * 4)[:380]
    assert len(jd) <= 400 and len(jd) >= 200
    assert "no_company_signal" in _codes(screen_jd(jd))


def test_long_jd_with_company_language_has_no_company_signal_flag():
    jd = "About us: we are Acme, " + "we build great products. " * 30
    assert "no_company_signal" not in _codes(screen_jd(jd))


# ── URL flags ────────────────────────────────────────────────────────────────

def test_shortened_url_info():
    flags = screen_jd("A perfectly normal long posting about engineering culture.", url="https://bit.ly/xyz")
    assert "shortened_url" in _codes(flags)


def test_repost_single_warning():
    history = {"https://jobs.lever.co/acme/123?src=li", "https://other.com/x"}
    flags = screen_jd(
        "We are Acme. About us: we build products. " * 8,
        url="https://www.jobs.lever.co/acme/123",
        history_urls=history,
    )
    reposts = [f for f in flags if f.code == "repost"]
    assert len(reposts) == 1
    assert reposts[0].level == "warn"


def test_no_repost_when_history_empty():
    flags = screen_jd("We are Acme. " * 40, url="https://jobs.lever.co/acme/9", history_urls=set())
    assert "repost" not in _codes(flags)


# ── general behaviour ────────────────────────────────────────────────────────

def test_empty_inputs_yield_no_flags():
    assert screen_jd("") == []
    assert screen_jd("", url=None, history_urls=None) == []


def test_flags_sorted_danger_first():
    jd = ("Pay a registration fee to start. Unlimited income! " * 3)[:250] + " Apply at x@gmail.com"
    flags = screen_jd(jd)
    levels = [f.level for f in flags]
    order = {"danger": 0, "warn": 1, "info": 2}
    assert levels == sorted(levels, key=order.get)  # type: ignore[arg-type]


def test_duplicate_codes_collapsed():
    jd = "Training fee required. Also there is a registration fee for materials."
    fee_flags = [f for f in screen_jd(jd) if f.code == "fee_request"]
    assert len(fee_flags) == 1


def test_sanitization_applied_before_matching():
    # Smart quotes / NBSP must not break phrase detection.
    jd = "Candidates must pay\u00a0a training\u2019fee? No wait \u2014 training fee applies."
    assert "fee_request" in _codes(screen_jd(jd))
