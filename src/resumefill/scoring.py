"""CV-vs-job-description fit scoring.

One LLM call produces a holistic 1-5 score across five fixed dimensions,
plus a verdict and evidence-based rationale. Decision support only — the
score never gates anything. Uses native structured output when available
and degrades to tolerant JSON parsing otherwise (same pattern as
``cv/analyzer.py``).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from resumefill.cv.analyzer import get_response_text, invoke_with_retry
from resumefill.text_utils import sanitize_text

# ── schema ───────────────────────────────────────────────────────────────────

Verdict = Literal["strong", "reasonable", "stretch", "skip"]

_VALID_VERDICTS: tuple[str, ...] = ("strong", "reasonable", "stretch", "skip")

_DIMENSIONS: tuple[str, ...] = (
    "skills_match",
    "experience_level",
    "domain_overlap",
    "growth_comp",
    "logistics",
)


class DimensionScore(BaseModel):
    """One scored dimension of the fit report."""

    name: str = ""
    score: float = 0.0
    rationale: str = ""


class FitReport(BaseModel):
    """Holistic CV-vs-JD fit assessment."""

    global_score: float = 0.0
    verdict: Verdict = "reasonable"
    dimensions: list[DimensionScore] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    summary: str = ""


# ── prompt ───────────────────────────────────────────────────────────────────

FIT_PROMPT = """\
You are a senior technical recruiter assessing how well a candidate fits ONE job posting.

**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{jd_text}

**SCORE these five dimensions** (each 1.0-5.0, one decimal at most), citing SPECIFIC \
evidence from the CV in every rationale:
- skills_match: required technologies vs candidate's skills
- experience_level: seniority demanded vs years/roles held
- domain_overlap: industry/domain of the role vs candidate's domain history
- growth_comp: growth trajectory and any compensation signals stated in the JD
- logistics: location/hybrid/remote/work-authorization expectations stated in the JD

Then give **global_score**: your HOLISTIC judgement (not an average — weigh what \
matters most for this pairing) and a **verdict**:
- "strong" (4.5+): apply now, tailor lightly
- "reasonable" (3.5-4.4): apply with tailoring
- "stretch" (2.5-3.4): apply only if strategically motivated
- "skip" (<2.5): poor use of application effort

List concrete **red_flags** from the JD itself (unpaid demands, misaligned level, \
hard blockers such as explicit no-sponsorship when the CV suggests it is needed).

**RETURN ONLY valid JSON** (no markdown fences):
{{
  "global_score": 4.0,
  "verdict": "reasonable",
  "dimensions": [
    {{"name": "skills_match", "score": 4.0, "rationale": "..."}},
    {{"name": "experience_level", "score": 4.0, "rationale": "..."}},
    {{"name": "domain_overlap", "score": 3.5, "rationale": "..."}},
    {{"name": "growth_comp", "score": 4.0, "rationale": "..."}},
    {{"name": "logistics", "score": 5.0, "rationale": "..."}}
  ],
  "red_flags": [],
  "summary": "2-3 sentence direct recommendation."
}}
"""

_MAX_JD_CHARS = 8000
_MIN_SCORE, _MAX_SCORE = 0.0, 5.0


# ── parsing helpers ──────────────────────────────────────────────────────────

def _clamp_score(value: float) -> float:
    return max(_MIN_SCORE, min(_MAX_SCORE, float(value)))


def _clamp_verdict(value: str) -> Verdict:
    normalized = (value or "").strip().lower()
    return normalized if normalized in _VALID_VERDICTS else "reasonable"  # type: ignore[return-value]


def _fill_dimensions(dimension_list: list[DimensionScore]) -> list[DimensionScore]:
    """Ensure all five canonical dimensions exist, in canonical order."""
    by_name = {(d.name or "").strip().lower(): d for d in dimension_list}
    filled: list[DimensionScore] = []
    for name in _DIMENSIONS:
        match = by_name.get(name)
        if match is not None:
            filled.append(
                DimensionScore(
                    name=name,
                    score=_clamp_score(match.score),
                    rationale=match.rationale,
                )
            )
        else:
            filled.append(
                DimensionScore(name=name, score=0.0, rationale="Not evaluated.")
            )
    return filled


def parse_fit_report(raw: str) -> FitReport:
    """Tolerantly build a FitReport from model output.

    Raises ``ValueError`` when no usable object can be recovered.
    """
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON found in scoring output: {raw[:200]!r}") from None
        data = json.loads(match.group())
    if not isinstance(data, dict):
        raise ValueError("Scoring output did not decode to a JSON object")

    dimensions_raw = data.get("dimensions") or []
    dimensions = [
        d if isinstance(d, DimensionScore) else DimensionScore.model_validate(d)
        for d in dimensions_raw
        if isinstance(d, dict)
    ]
    return FitReport(
        global_score=_clamp_score(float(data.get("global_score") or 0.0)),
        verdict=_clamp_verdict(str(data.get("verdict", ""))),
        dimensions=_fill_dimensions(dimensions),
        red_flags=[str(r) for r in data.get("red_flags", []) if str(r).strip()],
        summary=str(data.get("summary", "")).strip(),
    )


def _neutral_report(reason: str) -> FitReport:
    return FitReport(
        global_score=0.0,
        verdict="reasonable",
        dimensions=_fill_dimensions([]),
        red_flags=[],
        summary=f"Evaluation unavailable: {reason}",
    )


def _structured_chain(llm):
    binder = getattr(llm, "with_structured_output", None)
    if not callable(binder):
        return None
    try:
        return binder(FitReport)
    except Exception:  # noqa: BLE001 — provider quirks must not break scoring
        return None


def _is_rate_limit(error: BaseException) -> bool:
    message = str(error)
    return "429" in message or "RESOURCE_EXHAUSTED" in message


# ── entry point ──────────────────────────────────────────────────────────────

def evaluate_fit(
    cv_text: str,
    jd_text: str,
    llm,
    fallback_llm=None,
    sleep: Callable[[float], None] = time.sleep,
) -> FitReport:
    """Score CV-vs-JD fit. Requires a non-empty job description."""
    jd = sanitize_text(jd_text)
    if not jd:
        raise ValueError("evaluate_fit requires a non-empty job description")

    prompt = FIT_PROMPT.format(
        cv_text=sanitize_text(cv_text)[:8000],
        jd_text=jd[:_MAX_JD_CHARS],
    )

    chain = _structured_chain(llm)
    if chain is not None:
        fb_chain = _structured_chain(fallback_llm) if fallback_llm is not None else None
        try:
            result = invoke_with_retry(chain, prompt, fallback_llm=fb_chain, sleep=sleep)
            report = result if isinstance(result, FitReport) else FitReport.model_validate(result)
            return _finalize(report)
        except Exception as exc:  # noqa: BLE001 — deliberate degrade below
            if _is_rate_limit(exc):
                raise

    response = invoke_with_retry(llm, prompt, fallback_llm=fallback_llm, sleep=sleep)
    try:
        return parse_fit_report(get_response_text(response))
    except (ValueError, json.JSONDecodeError):
        return _neutral_report("model output could not be parsed")


def _finalize(report: FitReport) -> FitReport:
    report.global_score = _clamp_score(report.global_score)
    report.verdict = _clamp_verdict(str(report.verdict))
    report.dimensions = _fill_dimensions(report.dimensions)
    return report
