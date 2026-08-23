"""Streamlit UI for the Job Application Agent.

Thin presentation layer: configuration widgets, CV upload/analysis display,
and live agent progress. All business logic lives in ``resumefill.*``
modules.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import streamlit as st

# Windows: Proactor loop is required by Playwright subprocess plumbing;
# nest_asyncio lets asyncio.run work inside Streamlit's script thread.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import nest_asyncio  # noqa: E402  (must follow the policy setup)

nest_asyncio.apply()

from resumefill.agent.service import JobFormAgent  # noqa: E402
from resumefill.analytics import aggregate_runs  # noqa: E402
from resumefill.answers.generator import (  # noqa: E402
    QUESTION_SLOTS,
    generate_answer_pack,
    resolve_slots,
)
from resumefill.config import load_settings  # noqa: E402
from resumefill.cv.analyzer import analyze_cv, generate_style_profile  # noqa: E402
from resumefill.cv.extract import extract_from_pdf, extract_from_txt  # noqa: E402
from resumefill.llm.factory import create_analysis_llm  # noqa: E402
from resumefill.model_selection import (  # noqa: E402
    auto_select_model,
    discover_models,
    get_model_display_label,
)
from resumefill.profiles.store import ProfileStore  # noqa: E402

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

    defaults: dict[str, object] = {
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


# ── CV Profile ───────────────────────────────────────────────────────────────

PROFILE_NEW = "__new__"
profile_store = ProfileStore(settings.profiles_dir)
profiles = profile_store.list()  # [(slug, CvProfile)]


def _profile_label(slug: str) -> str:
    if slug == PROFILE_NEW:
        return "➕ New CV (analyze & save)"
    profile = next(p for s, p in profiles if s == slug)
    return f"{profile.name} — {profile.title or 'Professional'}"


profile_choice = st.selectbox(
    "👤 CV Profile",
    [PROFILE_NEW] + [slug for slug, _ in profiles],
    format_func=_profile_label,
    help="Reuse an analyzed profile without spending API calls, "
    "or analyze a new CV (saved automatically).",
)

if profile_choice == PROFILE_NEW:
    cv_upload = st.file_uploader("Upload CV (PDF or TXT)", type=["pdf", "txt"])
    if cv_upload is None and settings.default_cv_path() is not None:
        st.info("No upload — `data/cv.txt` will be used and saved as a profile.")
else:
    selected_profile = next(p for s, p in profiles if s == profile_choice)
    with st.expander("✏️ Profile details", expanded=True):
        edit_col1, edit_col2 = st.columns(2)
        edit_name = edit_col1.text_input(
            "Name", value=selected_profile.name, key=f"pf_{profile_choice}_name"
        )
        edit_email = edit_col2.text_input(
            "Email", value=selected_profile.email, key=f"pf_{profile_choice}_email"
        )
        edit_phone = edit_col1.text_input(
            "Phone", value=selected_profile.phone, key=f"pf_{profile_choice}_phone"
        )
        edit_title = edit_col2.text_input(
            "Title", value=selected_profile.title, key=f"pf_{profile_choice}_title"
        )
        save_col, delete_col = st.columns(2)
        if save_col.button("💾 Save changes", use_container_width=True):
            profile_store.update(
                profile_choice,
                name=edit_name,
                email=edit_email,
                phone=edit_phone,
                title=edit_title,
            )
            st.success("Profile updated.")
        if delete_col.button("🗑 Delete profile", use_container_width=True):
            profile_store.delete(profile_choice)
            st.rerun()

target_url = st.text_input(
    "Job Application URL",
    placeholder="https://careers.example.com/apply/12345",
)

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


def _stage_upload_file(cv_text: str, suffix: str = ".txt") -> Path:
    """Stage CV text for the agent's upload action (lives for this run)."""
    tmp_dir = tempfile.TemporaryDirectory(prefix="cv_", ignore_cleanup_errors=True)
    staged = Path(tmp_dir.name) / f"cv_upload{suffix}"
    staged.write_text(cv_text, encoding="utf-8")
    return staged


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_new_cv() -> tuple[str, str | None] | None:
    """Extract CV text from upload or fallback file; returns (text, sha256)."""
    if cv_upload is not None:
        raw = cv_upload.getvalue()
        if cv_upload.type == "application/pdf":
            extraction = extract_from_pdf(io.BytesIO(raw))
        else:
            extraction = extract_from_txt(raw)
    else:
        default_path = settings.default_cv_path()
        if default_path is None:
            st.error("Upload a CV or place `cv.txt` in `data/`.")
            return None
        st.info(f"Using local `{default_path.name}`.")
        raw = default_path.read_bytes()
        extraction = extract_from_txt(raw)

    if extraction.is_empty:
        st.error("Could not read any text from the CV.")
        return None
    for warning in extraction.warnings:
        st.warning(warning)
    return extraction.text, _sha256(raw)


def run_cv_analysis(cv_text: str) -> tuple[dict, str]:
    llm = create_analysis_llm(settings, st.session_state.selected_model)
    fallback_id = st.session_state.get("fallback_model")
    fallback_llm = create_analysis_llm(settings, fallback_id) if fallback_id else None

    with st.spinner("🧠 Analyzing CV — extracting skills, traits, and achievements…"):
        analysis = analyze_cv(cv_text, llm, fallback_llm=fallback_llm)
    with st.spinner("🎭 Building your communication persona…"):
        style_profile = generate_style_profile(analysis, llm, fallback_llm=fallback_llm)
    return analysis, style_profile


# ── Dry Run: draft & approve answers ─────────────────────────────────────────

st.markdown("### 🧪 Dry Run — Draft Answers (optional)")
job_description = st.text_area(
    "Job description (paste the posting — improves 'why this role' answers)",
    height=140,
    key="jd_text",
)

if st.button("🧪 Generate draft answers"):
    if not settings.has_api_key:
        st.error("GEMINI_API_KEY is not set — draft answers need it (see `.env.example`).")
        st.stop()

    if profile_choice == PROFILE_NEW:
        extracted = _extract_new_cv()
        if extracted is None:
            st.stop()
        dry_cv_text, dry_cv_sha = extracted
        dry_analysis, dry_style = run_cv_analysis(dry_cv_text)
        saved, saved_slug = profile_store.save(
            profile_store.build_from_analysis(dry_analysis, dry_style, dry_cv_text, dry_cv_sha)
        )
        st.success(f"👤 Profile saved: **{saved.name}** (`{saved_slug}`)")
        st.session_state["_dry_run_saved_slug"] = saved_slug
        st.session_state["_dry_run_saved_sha"] = dry_cv_sha
    else:
        base = next(p for s, p in profiles if s == profile_choice)
        dry_analysis, dry_style, dry_cv_text = base.analysis, base.style_profile, base.cv_text

    llm = create_analysis_llm(settings, st.session_state.selected_model)
    fb_id = st.session_state.get("fallback_model")
    fb_llm = create_analysis_llm(settings, fb_id) if fb_id else None
    with st.spinner("🧪 Drafting answers in your voice…"):
        pack = generate_answer_pack(
            analysis=dry_analysis,
            style_profile=dry_style,
            cv_text=dry_cv_text,
            llm=llm,
            fallback_llm=fb_llm,
            job_description=job_description or None,
        )

    order = [s for s in resolve_slots(job_description or None) if s in pack.answers]
    for slot in order:
        st.session_state.pop(f"ap_{slot}", None)  # show regenerated defaults
    st.session_state["answer_pack_order"] = order
    st.session_state["answer_pack"] = pack.answers
    if not pack.answers:
        st.warning("Model returned no usable answers — try regenerating.")

answer_order = st.session_state.get("answer_pack_order", [])
if answer_order:
    st.markdown(
        "**Review & edit** — approved answers are used *verbatim* on matching "
        "form questions; everything else is answered live from your persona."
    )
    for slot in answer_order:
        default = st.session_state["answer_pack"].get(slot, "")
        meta: Any = QUESTION_SLOTS.get(slot, {})
        st.text_area(
            f"{meta.get('label', slot)}  ·  {meta.get('hint', '')}",
            value=default,
            key=f"ap_{slot}",
            height=90,
        )

# ── Run History ──────────────────────────────────────────────────────────────

st.markdown("### 📈 Run History")
history = aggregate_runs(settings.log_dir)

metric_cols = st.columns(5)
metric_cols[0].metric("Total runs", history["total_runs"])
metric_cols[1].metric(
    "Success rate",
    f"{history['success_rate'] * 100:.0f}%" if history["success_rate"] is not None else "—",
)
metric_cols[2].metric("Avg steps", history["avg_steps"] if history["avg_steps"] is not None else "—")
metric_cols[3].metric("Total errors", history["total_errors"])
metric_cols[4].metric(
    "Total cost",
    f"${history['total_cost']:.4f}" if history.get("total_cost") is not None else "—",
)

if history["recent"]:
    st.dataframe(
        [record.as_row() for record in history["recent"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.caption("No completed runs yet — logs land in `logs/` after each run.")
if history["skipped_files"]:
    st.caption(f"ℹ️ {history['skipped_files']} unreadable/incomplete log file(s) ignored.")


if st.button("🚀 Start Agent", type="primary"):
    if not target_url:
        st.error("Enter a job application URL.")
        st.stop()
    if not settings.has_api_key and profile_choice == PROFILE_NEW:
        # A saved profile can run without LLM access; a new analysis cannot.
        st.error("GEMINI_API_KEY is not set — add it to `.env` (see `.env.example`).")
        st.stop()

    if profile_choice == PROFILE_NEW:
        # If dry-run already analyzed and saved this exact file, reuse it
        # to avoid paying for the same two LLM calls twice in one session.
        cached_slug = st.session_state.get("_dry_run_saved_slug")
        cached_sha = st.session_state.get("_dry_run_saved_sha")
        peek_raw = None
        if cv_upload is not None:
            peek_raw = cv_upload.getvalue()
        else:
            default_path = settings.default_cv_path()
            if default_path is not None:
                peek_raw = default_path.read_bytes()
        peek_sha = _sha256(peek_raw) if peek_raw is not None else None
        reused = False
        if cached_slug and peek_sha and peek_sha == cached_sha:
            try:
                cached = profile_store.load(cached_slug)
                analysis, style_profile, cv_text = (
                    cached.analysis,
                    cached.style_profile,
                    cached.cv_text,
                )
                st.info(f"Reusing profile `{cached_slug}` from dry-run — no re-analysis.")
                cv_file_path = _stage_upload_file(cv_text)
                reused = True
            except FileNotFoundError:
                reused = False
        if not reused:
            extracted = _extract_new_cv()
            if extracted is None:
                st.stop()
            cv_text, cv_sha = extracted
            analysis, style_profile = run_cv_analysis(cv_text)
            profile, profile_slug = profile_store.save(
                profile_store.build_from_analysis(analysis, style_profile, cv_text, cv_sha)
            )
            st.success(f"👤 Profile saved: **{profile.name}** (`{profile_slug}`)")
            cv_file_path = _stage_upload_file(cv_text)
    else:
        base_profile = next(p for s, p in profiles if s == profile_choice)
        # Use what is on screen; unsaved edits apply to this run only.
        profile = replace(
            base_profile,
            name=st.session_state.get(f"pf_{profile_choice}_name", base_profile.name),
            email=st.session_state.get(f"pf_{profile_choice}_email", base_profile.email),
            phone=st.session_state.get(f"pf_{profile_choice}_phone", base_profile.phone),
            title=st.session_state.get(f"pf_{profile_choice}_title", base_profile.title),
        )
        analysis, style_profile, cv_text = (
            profile.analysis,
            profile.style_profile,
            profile.cv_text,
        )
        cv_file_path = _stage_upload_file(cv_text)

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

    approved_answers = {
        slot: value.strip()
        for slot in st.session_state.get("answer_pack_order", [])
        if (value := st.session_state.get(f"ap_{slot}")) and value.strip()
    }
    if approved_answers:
        st.info(f"🧪 Using {len(approved_answers)} pre-approved answer(s) from dry run.")

    display_analysis(analysis, style_profile)

    with st.spinner("🚀 Agent is filling the form…"):
        result = asyncio.run(
            agent_service.run(
                target_url,
                cv_text,
                analysis,
                style_profile,
                cv_file_path=cv_file_path,
                pre_approved_answers=approved_answers or None,
                job_description=(job_description or None),
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
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Steps", summary["total_steps"])
        col_b.metric("Errors", summary["total_errors"])
        col_c.metric("Pages", summary["pages_visited"])
        usage = summary.get("usage") or {}
        col_d.metric(
            "Cost",
            f"${usage['total_cost']:.4f}" if usage.get("total_cost") is not None else "—",
        )
        st.caption(f"⏱️ Duration: {summary['elapsed_human']}")
        if usage.get("total_tokens") is not None:
            st.caption(f"🔢 Tokens: {usage['total_tokens']:,}")
        st.caption(f"📝 Full log: `{summary['log_file']}`")

    if result.success:
        st.balloons()
