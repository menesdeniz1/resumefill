"""Task-prompt construction for the form-filling agent.

Pure string assembly — no I/O — so prompt content is unit-testable.
"""

from __future__ import annotations

from resumefill.agent.scripts import VERIFY_FIELDS_JS, YESNO_JS


def format_education(analysis: dict) -> str:
    edu_list = analysis.get("education", [])
    if not edu_list:
        return "See CV"
    return "; ".join(
        f"{e.get('degree', '')} from {e.get('institution', '')}".strip(" from")
        for e in edu_list
    )


def build_task_prompt(
    cv_text: str,
    analysis: dict,
    style_profile: str,
    platform_tips: str,
    job_description: str | None = None,
) -> str:
    """Build the complete agent task prompt with persona and platform tips."""

    name = analysis.get("name", "the applicant")
    achievements = "\n".join(f"- {a}" for a in analysis.get("key_achievements", []))
    strengths = "\n".join(f"- {s}" for s in analysis.get("strengths", []))
    traits = ", ".join(analysis.get("personality_traits", []))
    skills = analysis.get("skills", {})
    technical = ", ".join(skills.get("technical", []))
    soft = ", ".join(skills.get("soft", []))
    education = format_education(analysis)

    if job_description and job_description.strip():
        jd_section = f"""
═══════════════════════════════════════════
 JOB DESCRIPTION — tailor answers to THIS role:
═══════════════════════════════════════════
{job_description.strip()}
"""
    else:
        jd_section = ""

    return f"""\
You are filling out a job application form for {name}. Here is the full CV:

{cv_text}

═══════════════════════════════════════════
 PERSONA — Answer open-ended questions in THIS style:
═══════════════════════════════════════════
{style_profile}

═══════════════════════════════════════════
 KEY FACTS — Reference these in answers:
═══════════════════════════════════════════
Name: {name}
Personality: {traits}
Technical Skills: {technical}
Soft Skills: {soft}
Education: {education}

Key Achievements:
{achievements}

Key Strengths:
{strengths}
{jd_section}
═══════════════════════════════════════════
 FORM FILLING RULES (CRITICAL):
═══════════════════════════════════════════

1. **Structured Fields** (name, email, phone, address, dropdowns):
   → Fill directly from the CV data above. Do NOT improvise.

2. **Open-Ended Questions** (textareas, "Tell us about yourself", "Why this role?"):
   → Answer in FIRST PERSON as {name}, following the PERSONA above.
   → Reference SPECIFIC achievements and projects from the CV.
   → Keep answers 2-5 sentences unless the field clearly expects more.
   → DO NOT write generic AI-sounding responses.
   → DO NOT start with "As a..." or "I am excited to..."

3. **"Why this company/role?"** questions:
   → Read the job page content visible on screen for company name and role details.
   → Connect YOUR specific skills/achievements to THEIR specific needs.
   → Be genuine, not flattering.

4. **Yes/No Buttons & Radio Buttons — CRITICAL:**
   → NEVER click Yes/No or radio buttons by element index — it rarely works.
   → ALWAYS use the `evaluate` action with the YESNO JavaScript provided below.
   → Run the YESNO JS AFTER filling text fields but BEFORE clicking Next.
   → "Have you worked with us before?" → "No" unless CV indicates otherwise.

5. **Address Fields:**
   → City and Street Address are DIFFERENT fields — do not repeat the city name.
   → If no street is in the CV, use a reasonable placeholder.

6. **MANDATORY VERIFICATION (run BEFORE every "Next" or page advance):**
   → Use the `evaluate` action with the VERIFY JavaScript provided below.
   → It returns a list of unfilled required fields and unchecked radios.
   → If the verification finds ANY issues, FIX them before clicking Next.
   → DO NOT skip pages or advance with unfilled fields.

7. **SPEED & EFFICIENCY:**
   → BATCH ACTIONS: Fill multiple fields in ONE step, not one at a time.
   → Fill name, email, phone, address ALL IN ONE STEP when possible.
   → Only click "Next" / "Continue" after verification passes.

8. **NEVER click Submit / Send Application.** The user will review and submit manually.

═══════════════════════════════════════════
 PLATFORM-SPECIFIC TIPS:
═══════════════════════════════════════════
{platform_tips}
"""


def build_yesno_section() -> str:
    """Appendix instructing the agent how to run the Yes/No handler JS."""
    return (
        "\n\n⚠️ YES/NO HANDLER JS — use this with the `evaluate` action "
        "on EVERY page AFTER filling text fields but BEFORE clicking Next:\n" + YESNO_JS
    )


def build_verify_section() -> str:
    """Appendix making the verification JS a mandatory pre-Next gate."""
    return (
        "\n\n✅ VERIFICATION JS — you MUST run this with `evaluate` BEFORE "
        "clicking Next on EVERY page. If it reports issues, fix them first:\n" + VERIFY_FIELDS_JS
    )


def build_upload_section(cv_file_path: str) -> str:
    """Appendix telling the agent which file to attach to upload fields."""
    return (
        f"\n\n📎 CV FILE FOR UPLOAD: {cv_file_path}\n"
        "When you see a Resume/CV upload field, use the upload_file action "
        "with this file path. This is the applicant's CV/resume file."
    )


def build_preapproved_section(answers: dict[str, str]) -> str:
    """Appendix with user-reviewed answers the agent must use verbatim.

    ``answers`` maps question slots (see resumefill.answers.generator) to
    approved answer text. Pure string assembly, unit-tested.
    """
    if not answers:
        return ""
    from resumefill.answers.generator import QUESTION_SLOTS

    lines = [
        "",
        "",
        "═══════════════════════════════════════════",
        " PRE-APPROVED ANSWERS — REVIEWED BY THE APPLICANT:",
        "═══════════════════════════════════════════",
        "When a question on the form matches one of these intents, use the",
        "approved answer VERBATIM. Only adjust obvious grammatical glue when",
        "the form forces it. For numeric fields (salary/notice), enter just",
        "the figure or phrase extracted from the answer.",
        "",
    ]
    for slot, answer in answers.items():
        meta = QUESTION_SLOTS.get(slot, {})
        label = meta.get("label", slot)
        hint = meta.get("hint", "")
        hint_text = f" Matches: {hint}" if hint else ""
        lines.append(f"• {label.upper()}{hint_text}")
        lines.append(f"  APPROVED: {answer.strip()}")
        lines.append("")
    return "\n".join(lines)
