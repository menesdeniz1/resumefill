"""Gemini-powered CV analysis: structured profile + communication persona."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable

from pydantic import BaseModel, Field

from resumefill.text_utils import sanitize_text

# ── Native structured-output schema ──────────────────────────────────────────
# Mirrors the JSON contract of CV_ANALYSIS_PROMPT. All fields default so a
# partially-filled model response can never crash downstream consumers,
# which read via ``analysis.get(...)``.

class EducationItem(BaseModel):
    institution: str = ""
    degree: str = ""
    gpa: str = ""
    notes: str = ""


class ExperienceItem(BaseModel):
    company: str = ""
    role: str = ""
    dates: str = ""
    highlights: list[str] = Field(default_factory=list)


class SkillGroups(BaseModel):
    technical: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    soft: list[str] = Field(default_factory=list)


class CvProfileSchema(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    title: str = ""
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    skills: SkillGroups = Field(default_factory=SkillGroups)
    languages: list[str] = Field(default_factory=list)
    key_achievements: list[str] = Field(default_factory=list)
    personality_traits: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    experience_summary: str = ""
    communication_style: str = ""


class RateLimitError(Exception):
    """Raised when an LLM call is rejected due to quota/rate limits."""


def _is_rate_limit(error: BaseException) -> bool:
    message = str(error)
    return "429" in message or "RESOURCE_EXHAUSTED" in message


def invoke_with_retry(
    llm,
    prompt: str,
    max_retries: int = 3,
    base_delay: float = 30.0,
    fallback_llm=None,
    sleep: Callable[[float], None] = time.sleep,
):
    """Invoke an LLM, switching to a fallback model on quota exhaustion.

    Without a fallback, rate-limit errors are retried with exponential
    backoff (honouring any ``retry in Xs`` hint from the API). Any other
    error propagates immediately.
    """
    for attempt in range(max_retries):
        try:
            return llm.invoke(prompt)
        except Exception as exc:  # noqa: BLE001 — LLM SDKs raise assorted types
            if not _is_rate_limit(exc):
                raise
            if fallback_llm is not None:
                llm, fallback_llm = fallback_llm, None
                continue
            delay = base_delay * (2**attempt)
            match = re.search(r"retry in ([\d.]+)s", str(exc), re.IGNORECASE)
            if match:
                delay = max(float(match.group(1)), delay)
            sleep(delay)
    return llm.invoke(prompt)


def get_response_text(response) -> str:
    """Extract plain text from LangChain chat responses of varying shapes."""
    content = response.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
            else:
                parts.append(str(part))
        return "\n".join(parts).strip()
    return str(content).strip()


def parse_profile_json(raw: str) -> dict:
    """Parse a JSON CV profile, tolerating markdown fences or stray prose.

    Raises ``ValueError`` when no JSON object can be recovered.
    """
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        profile = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in model output: {raw[:200]!r}") from None
        profile = json.loads(match.group())
    if not isinstance(profile, dict):
        raise ValueError("Model output did not decode to a JSON object")
    return profile


CV_ANALYSIS_PROMPT = """\
You are an expert HR analyst and career coach. Analyze the following CV/resume and extract a structured JSON profile.

**CV TEXT:**
{cv_text}

**INSTRUCTIONS:**
- Infer personality traits from the type of work, achievements, and skills listed.
- Identify leadership indicators (team lead, scrum master, mentoring, etc.)
- Identify collaboration indicators (team player, cross-functional, presentations, etc.)
- Extract quantifiable achievements with metrics when available.
- Determine communication style from the CV's writing (concise vs. verbose, technical vs. casual).

**RETURN ONLY valid JSON** with this exact structure (no markdown, no code fences):
{{
  "name": "Full Name",
  "email": "email@example.com",
  "phone": "+1234567890",
  "location": "City, Country",
  "title": "Current or target job title",
  "education": [
    {{"institution": "...", "degree": "...", "gpa": "...", "notes": "..."}}
  ],
  "experience": [
    {{
      "company": "...",
      "role": "...",
      "dates": "...",
      "highlights": ["achievement 1", "achievement 2"]
    }}
  ],
  "skills": {{
    "technical": ["Python", "C++", "..."],
    "tools": ["Git", "Docker", "..."],
    "soft": ["Leadership", "Problem Solving", "..."]
  }},
  "languages": ["English (Advanced)", "..."],
  "key_achievements": [
    "Achievement with metric (e.g., 'Reduced costs by 88%')"
  ],
  "personality_traits": [
    "Analytical problem solver",
    "Results-driven",
    "..."
  ],
  "strengths": [
    "What makes this candidate unique"
  ],
  "experience_summary": "A 2-3 sentence narrative of their career arc.",
  "communication_style": "Brief description: e.g., 'Concise, metric-driven, technically precise'"
}}
"""


STYLE_PROFILE_PROMPT = """\
You are creating a communication persona for a job applicant. Based on the analysis below, write a detailed persona description that captures HOW this person communicates.

**ANALYSIS:**
- Name: {name}
- Title: {title}
- Personality Traits: {traits}
- Communication Style: {comm_style}
- Key Achievements: {achievements}
- Strengths: {strengths}
- Experience Summary: {experience_summary}

**WRITE THE PERSONA** as a 2nd-person instruction paragraph (starting with "You are..."). Include:
1. Their default tone (formal/casual/technical/friendly)
2. How they structure answers (bullet points vs. narrative, short vs. long)
3. What they emphasize (metrics/impact/teamwork/innovation)
4. Vocabulary tendencies (technical jargon level, industry terms)
5. Answer length preference (1-2 sentences, 3-5 sentences, or paragraphs)
6. Cultural communication patterns if detectable
7. Confidence level (humble, balanced, assertive)

**CRITICAL:** This persona will be used to generate job application answers. Make it specific enough that answers will sound like this actual person, not a generic AI.

Return ONLY the persona paragraph, nothing else.
"""

# Minimal profile used when the analysis call fails entirely, so the agent
# can still run off the raw CV text instead of crashing.
_MINIMAL_PROFILE_TEMPLATE = {
    "name": "Unknown",
    "email": "",
    "phone": "",
    "location": "",
    "title": "",
    "skills": {"technical": [], "tools": [], "soft": []},
    "key_achievements": [],
    "personality_traits": [],
    "strengths": [],
    "communication_style": "Unknown",
}


def _structured_chain(llm):
    """Bind the profile schema when the client supports native structured
    output; ``None`` otherwise (caller degrades to text parsing)."""
    binder = getattr(llm, "with_structured_output", None)
    if not callable(binder):
        return None
    try:
        return binder(CvProfileSchema)
    except Exception:  # noqa: BLE001 — provider quirks must not break analysis
        return None


def _coerce_profile(result) -> dict:
    """Schema instance (or dict) → plain dict matching the legacy shape."""
    data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    return data


def analyze_cv(cv_text: str, llm, fallback_llm=None,
               sleep: Callable[[float], None] = time.sleep) -> dict:
    """Send CV text to Gemini and extract a structured profile dict.

    Prefers native structured output; on any non-quota failure of that path
    degrades to prompt-only JSON parsing with regex recovery.
    """
    prompt = CV_ANALYSIS_PROMPT.format(cv_text=sanitize_text(cv_text))

    chain = _structured_chain(llm)
    if chain is not None:
        fb_chain = _structured_chain(fallback_llm) if fallback_llm is not None else None
        try:
            result = invoke_with_retry(chain, prompt, fallback_llm=fb_chain, sleep=sleep)
            return _coerce_profile(result)
        except Exception as exc:  # noqa: BLE001 — deliberate degrade below
            if _is_rate_limit(exc):
                raise  # quota is shared by both paths — no point re-prompting

    response = invoke_with_retry(llm, prompt, fallback_llm=fallback_llm, sleep=sleep)
    try:
        return parse_profile_json(get_response_text(response))
    except (ValueError, json.JSONDecodeError):
        minimal = dict(_MINIMAL_PROFILE_TEMPLATE)
        minimal["experience_summary"] = cv_text[:500]
        return minimal


def generate_style_profile(analysis: dict, llm, fallback_llm=None) -> str:
    """Create a communication-style persona from a structured CV profile."""
    prompt = STYLE_PROFILE_PROMPT.format(
        name=analysis.get("name", "the applicant"),
        title=analysis.get("title", "professional"),
        traits=", ".join(analysis.get("personality_traits", [])),
        comm_style=analysis.get("communication_style", "professional"),
        achievements="; ".join(analysis.get("key_achievements", [])),
        strengths="; ".join(analysis.get("strengths", [])),
        experience_summary=analysis.get("experience_summary", ""),
    )
    response = invoke_with_retry(llm, prompt, fallback_llm=fallback_llm)
    return get_response_text(response)
