"""
CV Analyzer — Automatic personality & style extraction from any CV.

Uses Google Gemini to:
1. Extract structured data (name, skills, achievements, traits)
2. Build a communication-style persona
3. Answer open-ended questions in the applicant's voice
"""

import json
import re
import time


# ──────────────────────────────────────────────
#  Retry logic for rate-limited API calls
# ──────────────────────────────────────────────

def _invoke_with_retry(llm, prompt: str, max_retries: int = 3,
                       base_delay: float = 30.0, fallback_llm=None):
    """
    Invoke the LLM with automatic retry on rate-limit (429) errors.
    If a fallback_llm is provided, switches to it on quota exhaustion
    instead of retrying the same exhausted model.
    """
    for attempt in range(max_retries):
        try:
            return llm.invoke(prompt)
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                # If we have a fallback, switch immediately instead of waiting
                if fallback_llm is not None:
                    print(f"⚡ Primary model quota exhausted — switching to fallback model.")
                    llm = fallback_llm
                    fallback_llm = None  # Don't loop forever
                    continue
                # No fallback — retry with backoff
                delay = base_delay * (2 ** attempt)
                import re as _re
                match = _re.search(r"retry in ([\d.]+)s", error_str, _re.IGNORECASE)
                if match:
                    delay = max(float(match.group(1)), delay)
                print(f"⏳ Rate limited (attempt {attempt + 1}/{max_retries}). "
                      f"Retrying in {delay:.0f}s...")
                time.sleep(delay)
            else:
                raise  # Re-raise non-rate-limit errors
    # Final attempt without catching
    return llm.invoke(prompt)


def _get_text(response) -> str:
    """
    Safely extract text from an LLM response.
    Some models return content as a string, others as a list of parts.
    """
    content = response.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        # Join all text parts
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
            else:
                parts.append(str(part))
        return "\n".join(parts).strip()
    return str(content).strip()


# ──────────────────────────────────────────────
#  1. CV Analysis — Structured extraction
# ──────────────────────────────────────────────

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


def analyze_cv(cv_text: str, llm, fallback_llm=None) -> dict:
    """
    Send the CV to Gemini and extract a structured profile.

    Args:
        cv_text: Raw text of the CV/resume.
        llm: A LangChain-compatible chat model (e.g., ChatGoogleGenerativeAI).
        fallback_llm: Optional fallback model if primary hits quota.

    Returns:
        A dictionary with structured CV analysis.
    """
    prompt = CV_ANALYSIS_PROMPT.format(cv_text=cv_text)
    response = _invoke_with_retry(llm, prompt, fallback_llm=fallback_llm)

    raw = _get_text(response)

    # Strip markdown code fences if the model wraps it
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: try to extract JSON from the response
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        # Last resort: return minimal structure
        return {
            "name": "Unknown",
            "email": "",
            "phone": "",
            "location": "",
            "title": "",
            "skills": {"technical": [], "tools": [], "soft": []},
            "key_achievements": [],
            "personality_traits": [],
            "strengths": [],
            "experience_summary": cv_text[:500],
            "communication_style": "Unknown",
        }


# ──────────────────────────────────────────────
#  2. Style Profile — Persona generation
# ──────────────────────────────────────────────

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


def generate_style_profile(analysis: dict, llm, fallback_llm=None) -> str:
    """
    Create a communication-style persona from the CV analysis.

    Args:
        analysis: The structured dict from analyze_cv().
        llm: A LangChain-compatible chat model.
        fallback_llm: Optional fallback model if primary hits quota.

    Returns:
        A persona description string.
    """
    prompt = STYLE_PROFILE_PROMPT.format(
        name=analysis.get("name", "the applicant"),
        title=analysis.get("title", "professional"),
        traits=", ".join(analysis.get("personality_traits", [])),
        comm_style=analysis.get("communication_style", "professional"),
        achievements="; ".join(analysis.get("key_achievements", [])),
        strengths="; ".join(analysis.get("strengths", [])),
        experience_summary=analysis.get("experience_summary", ""),
    )
    response = _invoke_with_retry(llm, prompt, fallback_llm=fallback_llm)
    return _get_text(response)


# ──────────────────────────────────────────────
#  3. Answer Generation — Personalized Q&A
# ──────────────────────────────────────────────

ANSWER_PROMPT = """\
You are answering a job application question AS the applicant described below. Your answer must sound like it was written by this specific person, NOT by an AI assistant.

**PERSONA:**
{style_profile}

**APPLICANT FACTS:**
- Name: {name}
- Title: {title}
- Key Achievements: {achievements}
- Technical Skills: {technical_skills}
- Soft Skills: {soft_skills}
- Experience: {experience_summary}
- Education: {education}

**QUESTION:**
{question}

**RULES:**
1. Write in FIRST PERSON as the applicant.
2. Follow the persona's communication style exactly.
3. Reference SPECIFIC achievements/projects from the CV when relevant.
4. Keep the answer between 2-5 sentences unless the question clearly requires more.
5. Be genuine and conversational — avoid corporate buzzwords unless the persona uses them.
6. DO NOT start with "As a..." or "I am excited to..." — these are AI tells.
7. DO NOT mention that you are an AI or that this was generated.

**ANSWER (first person, no quotes):**
"""


def generate_answer(question: str, style_profile: str, analysis: dict, llm) -> str:
    """
    Generate a personalized answer to an open-ended question.

    Args:
        question: The question from the job application form.
        style_profile: The persona string from generate_style_profile().
        analysis: The structured dict from analyze_cv().
        llm: A LangChain-compatible chat model.

    Returns:
        A personalized answer string.
    """
    # Build education string
    edu_list = analysis.get("education", [])
    education_str = "; ".join(
        f"{e.get('degree', '')} from {e.get('institution', '')}"
        for e in edu_list
    ) if edu_list else "Not specified"

    prompt = ANSWER_PROMPT.format(
        style_profile=style_profile,
        name=analysis.get("name", ""),
        title=analysis.get("title", ""),
        achievements="; ".join(analysis.get("key_achievements", [])),
        technical_skills=", ".join(analysis.get("skills", {}).get("technical", [])),
        soft_skills=", ".join(analysis.get("skills", {}).get("soft", [])),
        experience_summary=analysis.get("experience_summary", ""),
        education=education_str,
        question=question,
    )
    response = _invoke_with_retry(llm, prompt)
    return _get_text(response)


# ──────────────────────────────────────────────
#  4. Platform-Specific Tips
# ──────────────────────────────────────────────

PLATFORM_TIPS = {
    "workday": """
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
- BEFORE clicking "Next": Run the radio button JS FIRST, then scroll down to check ALL fields.
""",
    "lever": """
LEVER-SPECIFIC:
- Forms are typically simpler — single page with text inputs and textareas.
- Resume upload is usually handled separately; focus on filling text fields.
- "Additional information" textarea: Use this to add a brief personal pitch.
- Links fields (LinkedIn, GitHub, Portfolio): Fill from CV data if available.
- Custom questions are usually free-text — use the persona for these.
""",
    "greenhouse": """
GREENHOUSE-SPECIFIC:
- Multi-page forms: Click "Next" or "Submit Application" to advance.
- Demographic questions (gender, race, veteran status): Select "Decline to self-identify" unless instructed otherwise.
- Cover letter field: Generate a 3-4 sentence pitch using the persona.
- Custom questions often use dropdowns — read all options before selecting.
- Some fields auto-populate from resume parsing — verify they're correct.
""",
    "linkedin": """
LINKEDIN EASY APPLY-SPECIFIC:
- Forms are usually 2-3 steps with minimal fields.
- "Why are you a good fit?" textarea: Use persona to write 2-3 sentences.
- Phone number format: Include country code.
- "Follow this company" checkbox: Leave as default.
- Additional questions vary by employer — use persona for open-ended ones.
- Resume is usually auto-attached; focus on text fields only.
""",
}


def get_platform_tips() -> str:
    """
    Return combined platform-specific instructions for all supported platforms.
    """
    sections = []
    for platform, tips in PLATFORM_TIPS.items():
        sections.append(tips.strip())
    return "\n\n".join(sections)
