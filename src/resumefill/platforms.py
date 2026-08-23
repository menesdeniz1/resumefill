"""Job-board platform detection and per-platform agent tips.

Only the tips for the *detected* platform (plus a small universal section)
are injected into the agent prompt — stuffing all four platforms' guidance
into every prompt wastes tokens and dilutes the model's attention.
"""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlparse


class Platform(StrEnum):
    WORKDAY = "workday"
    LEVER = "lever"
    GREENHOUSE = "greenhouse"
    LINKEDIN = "linkedin"
    GENERIC = "generic"


_HOST_HINTS: tuple[tuple[Platform, tuple[str, ...]], ...] = (
    (Platform.WORKDAY, ("myworkdayjobs.com", "wd1.", "wd3.", "wd5.", "myworkdaysite.com")),
    (Platform.LEVER, ("lever.co", "jobs.eu.lever.co")),
    (Platform.GREENHOUSE, ("greenhouse.io", "grnh.se", "greenhouse.io/embed")),
    (Platform.LINKEDIN, ("linkedin.com",)),
)


def detect_platform(url: str) -> Platform:
    """Identify the job-board platform from a URL's hostname."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return Platform.GENERIC
    if not host:
        return Platform.GENERIC
    for platform, hints in _HOST_HINTS:
        if any(host == hint or host.endswith("." + hint) or hint in host for hint in hints):
            return platform
    return Platform.GENERIC


PLATFORM_TIPS: dict[Platform, str] = {
    Platform.WORKDAY: """\
WORKDAY-SPECIFIC:

⚠️ RADIO BUTTONS (CRITICAL — Workday uses CUSTOM radio components, NOT standard HTML):
  DO NOT click radio buttons by index — it does not work on Workday.
  ALWAYS use the `evaluate` action with JavaScript to click radio buttons.
  The JavaScript should find elements with [role="radio"], match the answer text,
  and call .click() directly. Check aria-checked="true" after to confirm.
  If radio button JS is provided in the task, use that EXACT code with evaluate.

- "Have you worked with us before?" → Select "No" unless CV shows otherwise.
- Address fields: City and Street Address are DIFFERENT fields. Use a generic street if not in CV.
- Dropdown menus: Click to open, then click the option text.
- "How did you hear about us?" → Select "Job Board" or "LinkedIn" or "Company Website".
- Work authorization: Select based on CV's nationality/location context.
- BEFORE clicking "Next": Run the radio button JS FIRST, then scroll down to check ALL fields.""",
    Platform.LEVER: """\
LEVER-SPECIFIC:
- Forms are typically simpler — single page with text inputs and textareas.
- Resume upload is usually handled separately; focus on filling text fields.
- "Additional information" textarea: Use this to add a brief personal pitch.
- Links fields (LinkedIn, GitHub, Portfolio): Fill from CV data if available.
- Custom questions are usually free-text — use the persona for these.""",
    Platform.GREENHOUSE: """\
GREENHOUSE-SPECIFIC:
- Multi-page forms: Click "Next" or "Submit Application" to advance.
- Demographic questions (gender, race, veteran status): Select "Decline to self-identify" unless instructed otherwise.
- Cover letter field: Generate a 3-4 sentence pitch using the persona.
- Custom questions often use dropdowns — read all options before selecting.
- Some fields auto-populate from resume parsing — verify they're correct.""",
    Platform.LINKEDIN: """\
LINKEDIN EASY APPLY-SPECIFIC:
- Forms are usually 2-3 steps with minimal fields.
- "Why are you a good fit?" textarea: Use persona to write 2-3 sentences.
- Phone number format: Include country code.
- "Follow this company" checkbox: Leave as default.
- Additional questions vary by employer — use persona for open-ended ones.
- Resume is usually auto-attached; focus on text fields only.""",
    Platform.GENERIC: """\
GENERIC SITE GUIDANCE:
- Inspect each field's label and required markers before filling.
- Prefer native interactions (input/select) over JS injection when they work.
- Run the verification JS before advancing on multi-page forms.""",
}


def get_platform_tips(url: str) -> str:
    """Tips for the detected platform plus universal guidance."""
    platform = detect_platform(url)
    sections = [PLATFORM_TIPS[platform]]
    if platform != Platform.GENERIC:
        sections.append(PLATFORM_TIPS[Platform.GENERIC])
    return "\n\n".join(sections)
