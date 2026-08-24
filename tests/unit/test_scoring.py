"""Fit scoring: structured path, text fallback, clamping, neutral degrade."""

import json

import pytest
from fakes import FakeLLM, FakeResponse

from resumefill.scoring import (
    _DIMENSIONS,
    FitReport,
    evaluate_fit,
    parse_fit_report,
)


class FakeStructuredChain:
    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        outcome = self._outcomes.pop(0) if self._outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class StructuredCapableLLM(FakeLLM):
    def __init__(self, chain, *outcomes):
        super().__init__(*outcomes)
        self._chain = chain

    def with_structured_output(self, schema):
        assert schema is FitReport
        return self._chain


def _report_json(**overrides):
    data = {
        "global_score": 4.2,
        "verdict": "reasonable",
        "dimensions": [
            {"name": name, "score": 4.0, "rationale": "evidence"}
            for name in _DIMENSIONS
        ],
        "red_flags": [],
        "summary": "Solid fit; apply with tailoring.",
    }
    data.update(overrides)
    return data


def test_evaluate_requires_jd():
    with pytest.raises(ValueError):
        evaluate_fit("CV", "   ", FakeLLM())


def test_structured_path_maps_report_without_text_fallback():
    report = FitReport.model_validate(_report_json())
    chain = FakeStructuredChain(report)
    llm = StructuredCapableLLM(chain)

    result = evaluate_fit("CV TEXT", "JD TEXT", llm)

    assert result.global_score == pytest.approx(4.2)
    assert result.verdict == "reasonable"
    assert len(result.dimensions) == 5
    assert chain.calls and llm.calls == []


def test_text_fallback_parses_fenced_json():
    import json

    llm = StructuredCapableLLM(
        FakeStructuredChain(ValueError("schema unsupported")),
        FakeResponse("```json\n" + json.dumps(_report_json()) + "\n```"),
    )
    result = evaluate_fit("CV", "JD", llm)
    assert result.verdict == "reasonable"
    assert result.summary.startswith("Solid fit")
    assert len(llm.calls) == 1


def test_missing_dimensions_filled_in_canonical_order():
    partial = _report_json()
    partial["dimensions"] = [{"name": "skills_match", "score": 3.0, "rationale": "ok"}]
    result = parse_fit_report(__import__("json").dumps(partial))
    assert [d.name for d in result.dimensions] == list(_DIMENSIONS)
    unfilled = [d for d in result.dimensions if d.name != "skills_match"]
    assert all(d.rationale == "Not evaluated." for d in unfilled)


def test_invalid_verdict_and_score_clamped():
    raw = _report_json(global_score=9.7, verdict="amazing")
    report = parse_fit_report(json.dumps(raw))
    assert report.verdict == "reasonable"
    assert report.global_score == pytest.approx(5.0)


def test_broken_output_yields_neutral_report_not_exception():
    llm = StructuredCapableLLM(
        FakeStructuredChain(ValueError("no schema")),
        FakeResponse("the model rambled without any json at all"),
    )
    result = evaluate_fit("CV", "JD", llm)
    assert result.global_score == 0.0
    assert "unavailable" in result.summary.lower()


def test_prompt_contains_cv_and_jd_and_dimensions():
    seen_prompts: list[str] = []

    class RecordingChain(FakeStructuredChain):
        def invoke(self, prompt):
            seen_prompts.append(prompt)
            return FitReport.model_validate(_report_json())

    llm = StructuredCapableLLM(RecordingChain(None))
    evaluate_fit("MY CV CONTENT", "MY JD CONTENT", llm)
    prompt = seen_prompts[0]
    assert "MY CV CONTENT" in prompt and "MY JD CONTENT" in prompt
    for dim in _DIMENSIONS:
        assert dim in prompt
