from resumefill.agent.prompts import (
    build_task_prompt,
    build_upload_section,
    build_verify_section,
    build_yesno_section,
    format_education,
)
from resumefill.platforms import get_platform_tips

ANALYSIS = {
    "name": "Mücahid Enes Deniz",
    "title": "Software Engineer",
    "skills": {"technical": ["C++", "Python"], "soft": ["Leadership"]},
    "personality_traits": ["Analytical"],
    "strengths": ["Bridges hardware and AI"],
    "key_achievements": ["Reduced costs by 88%"],
    "education": [{"institution": "BAU", "degree": "B.Sc."}],
}


def test_prompt_contains_persona_cv_and_key_facts():
    prompt = build_task_prompt("CV TEXT HERE", ANALYSIS, "PERSONA TEXT", "TIPS")
    assert "CV TEXT HERE" in prompt
    assert "PERSONA TEXT" in prompt
    assert "Mücahid Enes Deniz" in prompt
    assert "Reduced costs by 88%" in prompt
    assert "B.Sc. from BAU" in prompt
    assert "C++, Python" in prompt


def test_prompt_contains_never_submit_rule():
    prompt = build_task_prompt("cv", ANALYSIS, "persona", "tips")
    assert "NEVER click Submit" in prompt


def test_prompt_scopes_platform_tips():
    tips = get_platform_tips("https://jobs.lever.co/acme/1")
    prompt = build_task_prompt("cv", ANALYSIS, "persona", tips)
    assert "LEVER-SPECIFIC" in prompt
    assert "WORKDAY-SPECIFIC" not in prompt


def test_education_formats_and_defaults():
    assert format_education(ANALYSIS) == "B.Sc. from BAU"
    assert format_education({}) == "See CV"


def test_appendix_sections():
    assert "YESNO_JS_MARKER" not in build_yesno_section()
    yesno = build_yesno_section()
    verify = build_verify_section()
    assert "evaluate" in yesno and "YES/NO HANDLER JS" in yesno
    assert "VERIFICATION JS" in verify
    upload = build_upload_section("/tmp/cv.pdf")
    assert "/tmp/cv.pdf" in upload
