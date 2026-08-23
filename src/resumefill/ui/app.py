"""Streamlit UI for the Job Application Agent.

Thin presentation layer: configuration widgets, CV upload/analysis display,
and live agent progress. All business logic lives in ``resumefill.*``
modules.
"""

from __future__ import annotations

import asyncio
import io
import sys
import tempfile
from pathlib import Path

import streamlit as st

# Windows: Proactor loop is required by Playwright subprocess plumbing;
# nest_asyncio lets asyncio.run work inside Streamlit's script thread.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import nest_asyncio  # noqa: E402  (must follow the policy setup)

nest_asyncio.apply()

from resumefill.agent.service import JobFormAgent  # noqa: E402
from resumefill.config import load_settings  # noqa: E402
from resumefill.cv.analyzer import analyze_cv, generate_style_profile  # noqa: E402
from resumefill.cv.extract import extract_from_pdf, extract_from_txt  # noqa: E402
from resumefill.llm.factory import create_analysis_llm  # noqa: E402
from resumefill.model_selection import (  # noqa: E402
    auto_select_model,
    discover_models,
    get_model_display_label,
)

settings = load_settings()

st.set_page_config(
    page_title="Job Application Agent",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🤖 Job Application Agent")
st.markdown(
    "**Powered by Google Gemini Flash** · Analyzes your CV, builds your persona, "
    "and fills job forms in your personal style."
)


def _apply_auto_selection(api_key: str) -> None:
    """Probe models once per session and store primary/fallback choices."""
    with st.spinner("🔍 Auto-detecting best models…"):
        if not api_key:
            st.session_state.model_status = "❌ No API key — set GEMINI_API_KEY in .env"
            return
        primary, fallback, tertiary, results = auto_select_model(api_key)
        st.session_state.probe_results = results
        if primary:
            st.session_state.selected_model = primary
            st.session_state.fallback_model = fallback
            st.session_state.tertiary_model = tertiary
            parts = [f"✅ {primary}"]
            if fallback:
                parts.append(f"Fallback: {fallback}")
            if tertiary:
                parts.append(f"Tertiary: {tertiary}")
            st.session_state.model_status = " · ".join(parts)
        else:
            st.session_state.model_status = "❌ No models available — using default"
        st.session_state.available_models = discover_models(api_key)


with st.sidebar:
    st.header("⚙️ Settings")
    st.markdown("### 🧠 Model Selection")

    defaults = {
        "selected_model": settings.default_model,
        "fallback_model": None,
        "tertiary_model": None,
        "available_models": [],
        "probe_results": [],
        "model_status": "Not checked",
        "auto_selected": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    if not st.session_state.auto_selected:
        st.session_state.auto_selected = True
        _apply_auto_selection(settings.gemini_api_key)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Discover", use_container_width=True):
            with st.spinner("Scanning models…"):
                st.session_state.available_models = discover_models(settings.gemini_api_key)
                st.session_state.model_status = (
                    f"Found {len(st.session_state.available_models)} models"
                )
    with col2:
        if st.button("⚡ Re-probe", use_container_width=True):
            _apply_auto_selection(settings.gemini_api_key)

    if st.session_state.available_models:
        model_ids = [m["id"] for m in st.session_state.available_models]
        labels = [get_model_display_label(m) for m in st.session_state.available_models]
        current = st.session_state.selected_model
        default_idx = model_ids.index(current) if current in model_ids else 0
        chosen_label = st.selectbox("Primary Model", labels, index=default_idx)
        st.session_state.selected_model = model_ids[labels.index(chosen_label)]
    else:
        st.session_state.selected_model = st.text_input(
            "Model ID", value=st.session_state.selected_model
        )

    st.caption(f"🟢 Primary: **{st.session_state.selected_model}**")
    if st.session_state.fallback_model:
        st.caption(f"🟡 Fallback: **{st.session_state.fallback_model}**")
    if st.session_state.model_status != "Not checked":
        st.caption(f"Status: {st.session_state.model_status}")

    if st.session_state.probe_results:
        with st.expander("📊 Probe Results", expanded=False):
            for r in st.session_state.probe_results:
                icon = "✅" if r["available"] else "❌"
                err = f" — {r['error']}" if r.get("error") else ""
                st.markdown(f"{icon} **{r['id']}** ({r['response_time']}s){err}")

    st.markdown("---")
    st.warning("🔒 Safety: Submit is blocked in code and never clicked")
    st.markdown("---")
    st.markdown("### Supported Platforms")
    st.markdown("✅ Workday\n✅ Lever\n✅ Greenhouse\n✅ LinkedIn Easy Apply")


col1, col2 = st.columns(2)
with col1:
    target_url = st.text_input(
        "Job Application URL",
        placeholder="https://careers.example.com/apply/12345",
    )
    cv_upload = st.file_uploader("Upload CV (PDF or TXT)", type=["pdf", "txt"])
with col2:
    st.markdown("### 📋 Agent Log")
    log_container = st.container()


def display_analysis(analysis: dict, style_profile: str) -> None:
    with st.expander("🧠 CV Analysis Results", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**Name:** {analysis.get('name', 'N/A')}")
            st.markdown(f"**Title:** {analysis.get('title', 'N/A')}")
            st.markdown(f"**Location:** {analysis.get('location', 'N/A')}")
            st.markdown(
                f"**Communication Style:** {analysis.get('communication_style', 'N/A')}"
            )
        with col_b:
            st.markdown("**Personality Traits:**")
            for trait in analysis.get("personality_traits", []):
                st.markdown(f"- {trait}")
            st.markdown("**Key Strengths:**")
            for s in analysis.get("strengths", []):
                st.markdown(f"- {s}")
        st.markdown("**Key Achievements:**")
        for ach in analysis.get("key_achievements", []):
            st.markdown(f"- 🏆 {ach}")

    with st.expander("🎭 Generated Persona", expanded=False):
        st.markdown(style_profile)


def resolve_cv() -> tuple[str, Path | None] | None:
    """Extract CV text and stage an uploadable copy; shows errors inline."""
    if cv_upload is not None:
        suffix = ".pdf" if cv_upload.type == "application/pdf" else ".txt"
        # Lives for this whole script run; the agent needs the file until
        # its upload action completes.
        tmp_dir = tempfile.TemporaryDirectory(prefix="cv_", ignore_cleanup_errors=True)
        staged = Path(tmp_dir.name) / f"cv_upload{suffix}"
        staged.write_bytes(cv_upload.getvalue())

        if suffix == ".pdf":
            extraction = extract_from_pdf(io.BytesIO(cv_upload.getvalue()))
        else:
            extraction = extract_from_txt(cv_upload.getvalue())
        if extraction.is_empty:
            st.error("Could not read any text from the uploaded CV.")
            return None
        for warning in extraction.warnings:
            st.warning(warning)
        return extraction.text, staged

    default_path = settings.default_cv_path()
    if default_path is None:
        st.error("Upload a CV or place `cv.txt` in the project folder.")
        return None
    st.info(f"Using local `{default_path.name}`.")
    extraction = extract_from_txt(default_path.read_bytes())
    for warning in extraction.warnings:
        st.warning(warning)
    return extraction.text, default_path


def run_cv_analysis(cv_text: str) -> tuple[dict, str]:
    llm = create_analysis_llm(settings, st.session_state.selected_model)
    fallback_id = st.session_state.get("fallback_model")
    fallback_llm = create_analysis_llm(settings, fallback_id) if fallback_id else None

    with st.spinner("🧠 Analyzing CV — extracting skills, traits, and achievements…"):
        analysis = analyze_cv(cv_text, llm, fallback_llm=fallback_llm)
    with st.spinner("🎭 Building your communication persona…"):
        style_profile = generate_style_profile(analysis, llm, fallback_llm=fallback_llm)
    return analysis, style_profile


if st.button("🚀 Start Agent", type="primary"):
    if not target_url:
        st.error("Enter a job application URL.")
        st.stop()
    if not settings.has_api_key:
        st.error("GEMINI_API_KEY is not set — add it to `.env` (see `.env.example`).")
        st.stop()

    resolved = resolve_cv()
    if resolved is None:
        st.stop()
    cv_text, cv_file_path = resolved

    agent_service = JobFormAgent(settings)
    logger = agent_service.build_logger(
        target_url,
        model_id=st.session_state.selected_model,
        fallback_model_id=st.session_state.get("fallback_model"),
    )
    st.caption(f"📝 Logging to: `{logger.filepath}`")

    async def on_step(step_num: int, output, page_url: str) -> None:
        with log_container:
            with st.chat_message("assistant"):
                st.write(f"**Step {step_num}**")
                goal = getattr(output, "next_goal", None) or getattr(output, "thinking", "…")
                st.code(goal, language="text")

    analysis, style_profile = run_cv_analysis(cv_text)
    display_analysis(analysis, style_profile)

    with st.spinner("🚀 Agent is filling the form…"):
        result = asyncio.run(
            agent_service.run(
                target_url,
                cv_text,
                analysis,
                style_profile,
                cv_file_path=cv_file_path,
                model_id=st.session_state.selected_model,
                fallback_model_id=st.session_state.get("fallback_model"),
                logger=logger,
                on_step=on_step,
            )
        )

    if result.success:
        st.success("✅ Done! Review the form and submit manually.")
    else:
        st.error(f"❌ Agent stopped: {result.error}")

    summary = result.summary
    with st.expander("📊 Run Summary", expanded=True):
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Steps", summary["total_steps"])
        col_b.metric("Errors", summary["total_errors"])
        col_c.metric("Pages", summary["pages_visited"])
        st.caption(f"⏱️ Duration: {summary['elapsed_human']}")
        st.caption(f"📝 Full log: `{summary['log_file']}`")

    if result.success:
        st.balloons()
