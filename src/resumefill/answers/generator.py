"""Pre-generated, user-editable answers to common application questions."""

from __future__ import annotations

from dataclasses import dataclass

from resumefill.cv.analyzer import (
    get_response_text,
    invoke_with_retry,
    parse_profile_json,
)

# Ordered question slots. ``requires_jd`` slots are skipped when no job
# description was supplied — vague generic answers are exactly what this
# product exists to avoid.
QUESTION_SLOTS: dict[str, dict[str, str]] = {
    "about_you": {
        "label": "About you",
        "hint": '"Tell us about yourself", "Summary", "Profile"',
        "requires_jd": False,
    },
    "strengths": {
        "label": "Key strengths",
        "hint": '"What are your strengths?"',
        "requires_jd": False,
    },
    "weakness": {
        "label": "A weakness",
        "hint": '"What is your greatest weakness?"',
        "requires_jd": False,
    },
    "why_this_role": {
        "label": "Why this role/company",
        "hint": '"Why do you want this role?", "Why our company?"',
        "requires_jd": True,
    },
    "notice_period": {
        "label": "Notice period",
        "hint": 'Short factual answer, e.g. "Two weeks".',
        "requires_jd": False,
    },
    "salary_expectation": {
        "label": "Salary expectation",
        "hint": "One sentence; include a concrete range.",
        "requires_jd": False,
    },
    "team_conflict": {
        "label": "Handling disagreement",
        "hint": '"Describe a conflict with a colleague and how you resolved it."',
        "requires_jd": False,
    },
    "why_leaving": {
        "label": "Why leaving current job",
        "hint": '"Why are you leaving your current position?"',
        "requires_jd": False,
    },
}


@dataclass
class AnswerPack:
    """Generated draft answers keyed by question slot."""

    answers: dict[str, str]
    used_job_description: bool


ANSWER_PACK_PROMPT = """\
You are drafting job-application answers AS the applicant described below. \
The applicant will review and edit these drafts before anything is submitted.

**PERSONA (how they write):**
{style_profile}

**CV TEXT:**
{cv_text}

{jd_section}
**GENERATE ANSWERS** for exactly these slots:
{slot_list}

**RULES:**
1. Write in FIRST PERSON as the applicant, following the PERSONA's style.
2. Reference SPECIFIC achievements/projects from the CV.
3. Open-ended answers: 2-4 sentences. Factual ones (notice period, salary): one short sentence.
4. Be genuine — DO NOT start with "As a..." or "I am excited to...", no corporate buzzword soup.
{jd_rule}
**RETURN ONLY valid JSON** (no markdown fences):
{{
  "answers": [
    {{"type": "<slot-name>", "answer": "<the answer>"}},
    ...
  ]
}}
"""


def _slot_list_text(slots: list[str]) -> str:
    return "\n".join(
        f'- "{slot}" ({QUESTION_SLOTS[slot]["label"]}) — {QUESTION_SLOTS[slot]["hint"]}'
        for slot in slots
    )


def resolve_slots(job_description: str | None) -> list[str]:
    """Slots applicable for the given inputs."""
    has_jd = bool(job_description and job_description.strip())
    return [
        slot
        for slot, meta in QUESTION_SLOTS.items()
        if not meta["requires_jd"] or has_jd
    ]


def build_jd_section(job_description: str | None) -> str:
    if not job_description or not job_description.strip():
        return ""
    return f"**JOB DESCRIPTION (tailor answers to THIS role):**\n{job_description.strip()}\n\n"


def build_jd_rule(job_description: str | None) -> str:
    if job_description and job_description.strip():
        return (
            "5. For why_this_role: connect the applicant's specific skills and achievements "
            "to THIS job description's requirements.\n"
        )
    return ""


def parse_answer_pack(raw: str, expected_slots: list[str]) -> dict[str, str]:
    """Parse generator output into ``{{slot: answer}}``, dropping junk."""
    parsed = parse_profile_json(raw)  # raises ValueError when unrecoverable
    raw_answers = parsed.get("answers")
    if not isinstance(raw_answers, list):
        raise ValueError("Model output missing 'answers' list")
    allowed = set(expected_slots)
    answers: dict[str, str] = {}
    for item in raw_answers:
        if not isinstance(item, dict):
            continue
        slot = str(item.get("type", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if slot in allowed and answer:
            answers[slot] = answer
    return answers


def generate_answer_pack(
    analysis: dict,
    style_profile: str,
    cv_text: str,
    llm,
    fallback_llm=None,
    job_description: str | None = None,
) -> AnswerPack:
    """Draft answers for all applicable slots in a single LLM call."""
    slots = resolve_slots(job_description)
    prompt = ANSWER_PACK_PROMPT.format(
        style_profile=style_profile,
        cv_text=cv_text[:6000],
        jd_section=build_jd_section(job_description),
        slot_list=_slot_list_text(slots),
        jd_rule=build_jd_rule(job_description),
    )
    response = invoke_with_retry(llm, prompt, fallback_llm=fallback_llm)
    answers = parse_answer_pack(get_response_text(response), slots)
    return AnswerPack(answers=answers, used_job_description=bool(job_description and job_description.strip()))
