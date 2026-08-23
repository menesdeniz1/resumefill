"""Answer pack generation, parsing and prompt embedding."""

import pytest
from fakes import FakeLLM, FakeResponse

from resumefill.agent.prompts import build_preapproved_section
from resumefill.answers.generator import (
    QUESTION_SLOTS,
    AnswerPack,
    generate_answer_pack,
    parse_answer_pack,
    resolve_slots,
)


def test_resolve_slots_excludes_jd_only_slots_without_jd():
    slots = resolve_slots(None)
    assert "why_this_role" not in slots
    assert "about_you" in slots
    assert resolve_slots("") == resolve_slots(None)


def test_resolve_slots_includes_all_with_jd():
    assert "why_this_role" in resolve_slots("We need a C++ engineer...")


def test_parse_answer_pack_filters_unknown_and_empty():
    raw = """{"answers": [
        {"type": "about_you", "answer": "I build vision systems."},
        {"type": "unknown_slot", "answer": "junk"},
        {"type": "strengths", "answer": "   "},
        "not-a-dict"
    ]}"""
    answers = parse_answer_pack(raw, ["about_you", "strengths"])
    assert answers == {"about_you": "I build vision systems."}


def test_parse_answer_pack_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_answer_pack("no json here", ["about_you"])


def test_generate_answer_pack_single_llm_call():
    canned = """{"answers": [
        {"type": "about_you", "answer": "Vision + industrial AI engineer."},
        {"type": "notice_period", "answer": "Two weeks."}
    ]}"""
    llm = FakeLLM(FakeResponse(canned))
    pack = generate_answer_pack(
        analysis={"name": "T"},
        style_profile="persona",
        cv_text="CV TEXT",
        llm=llm,
    )
    assert isinstance(pack, AnswerPack)
    assert pack.answers["notice_period"] == "Two weeks."
    assert not pack.used_job_description
    assert len(llm.calls) == 1
    prompt = llm.calls[0]
    assert "persona" in prompt and "CV TEXT" in prompt
    assert '"why_this_role"' not in prompt  # JD-only slot excluded from instructions


def test_generate_answer_pack_with_jd():
    canned = '{"answers": [{"type": "why_this_role", "answer": "Your GenAI roadmap matches my AOI work."}]}'
    llm = FakeLLM(FakeResponse(canned))
    pack = generate_answer_pack(
        analysis={}, style_profile="p", cv_text="c", llm=llm,
        job_description="GenAI Data Analyst role...",
    )
    assert pack.used_job_description
    assert pack.answers["why_this_role"].startswith("Your GenAI")
    assert "JOB DESCRIPTION" in llm.calls[0]


def test_preapproved_section_embeds_answers_verbatim():
    section = build_preapproved_section({"about_you": "I ship AOI systems."})
    assert "PRE-APPROVED ANSWERS" in section
    assert "VERBATIM" in section
    assert "I ship AOI systems." in section
    assert "ABOUT YOU" in section


def test_preapproved_section_empty_when_no_answers():
    assert build_preapproved_section({}) == ""
    assert build_preapproved_section(None) == ""


def test_every_slot_has_metadata():
    for slot, meta in QUESTION_SLOTS.items():
        assert meta["label"] and meta["hint"], slot
        assert isinstance(meta["requires_jd"], bool)
