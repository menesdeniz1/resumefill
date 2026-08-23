import pytest
from fakes import FakeLLM, FakeResponse

from resumefill.cv.analyzer import (
    get_response_text,
    invoke_with_retry,
    parse_profile_json,
)


def _rate_limit():
    return RuntimeError("429 RESOURCE_EXHAUSTED, retry in 7.0s")


class _NoSleep:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def test_invoke_retries_on_rate_limit_then_succeeds():
    sleeper = _NoSleep()
    llm = FakeLLM(_rate_limit(), _rate_limit(), FakeResponse("ok"))
    response = invoke_with_retry(llm, "p", base_delay=2.0, sleep=sleeper)
    assert get_response_text(response) == "ok"
    assert llm.calls == ["p", "p", "p"]
    # exponential backoff: 2s then 4s; API hint (7s) is respected when larger
    assert len(sleeper.calls) == 2


def test_invoke_switches_to_fallback_without_sleeping():
    sleeper = _NoSleep()
    primary = FakeLLM(_rate_limit())
    fallback = FakeLLM(FakeResponse("from-fallback"))
    response = invoke_with_retry(
        primary, "p", fallback_llm=fallback, sleep=sleeper
    )
    assert get_response_text(response) == "from-fallback"
    assert sleeper.calls == []
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_invoke_raises_non_rate_limit_errors_immediately():
    llm = FakeLLM(ValueError("bad request"))
    with pytest.raises(ValueError):
        invoke_with_retry(llm, "p", sleep=_NoSleep())
    assert len(llm.calls) == 1


def test_parse_profile_json_variants():
    plain = '{"name": "A"}'
    fenced = "```json\n{\"name\": \"A\"}\n```"
    prose = 'Here you go:\n{"name": "A"}\nDone.'
    for variant in (plain, fenced, prose):
        assert parse_profile_json(variant) == {"name": "A"}


def test_parse_profile_json_invalid_raises_valueerror():
    with pytest.raises(ValueError):
        parse_profile_json("not json at all")


def test_get_response_text_handles_part_lists():
    assert get_response_text(FakeResponse("plain")) == "plain"
    parts = FakeResponse(["a", {"text": "b"}, "c"])
    assert get_response_text(parts) == "a\nb\nc"
