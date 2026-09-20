import streamlit as st
import asyncio
import nest_asyncio
import sys
import os
import json
import tempfile
import threading
import http.server
import functools
from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatGoogle
from browser_use.browser.profile import BrowserProfile
from langchain_google_genai import ChatGoogleGenerativeAI
from pypdf import PdfReader

from cv_analyzer import analyze_cv, generate_style_profile, get_platform_tips
from model_selector import discover_models, probe_model, auto_select_model, get_model_display_label
from agent_logger import AgentLogger

# --- Platform Fixes ---
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
nest_asyncio.apply()

# --- Config ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_MODEL = "gemini-flash-latest"


# ──────────────────────────────────────────────
#  Utilities
# ──────────────────────────────────────────────

def read_file(path: str) -> str | None:
    """Read a UTF-8 text file. Returns None if not found."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def extract_pdf_text(file_stream) -> str | None:
    """Extract all text from a PDF upload."""
    try:
        reader = PdfReader(file_stream)
        return "\n".join(page.extract_text() for page in reader.pages)
    except Exception:
        return None


_server_started = False

def start_local_server(directory: str, port: int = 8000):
    """Start a background HTTP server to serve local HTML files."""
    global _server_started
    if _server_started:
        return
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=directory
    )
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _server_started = True


def get_llm(model_id: str | None = None):
    """Create a Gemini LLM for CV analysis (standalone use)."""
    selected = model_id or st.session_state.get("selected_model", DEFAULT_MODEL)
    return ChatGoogleGenerativeAI(
        model=selected,
        google_api_key=GEMINI_API_KEY,
        temperature=0.3,
    )


def get_agent_llm(model_id: str | None = None):
    """Create a Gemini LLM for the browser-use Agent (needs .provider attribute)."""
    selected = model_id or st.session_state.get("selected_model", DEFAULT_MODEL)
    return ChatGoogle(
        model=selected,
        api_key=GEMINI_API_KEY,
        temperature=0.3,
    )


# ──────────────────────────────────────────────
#  UI
# ──────────────────────────────────────────────

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

with st.sidebar:
    st.header("⚙️ Settings")

    # --- Model Selection ---
    st.markdown("### 🧠 Model Selection")

    # Initialize session state
    if "selected_model" not in st.session_state:
        st.session_state.selected_model = DEFAULT_MODEL
    if "fallback_model" not in st.session_state:
        st.session_state.fallback_model = None
    if "available_models" not in st.session_state:
        st.session_state.available_models = []
    if "probe_results" not in st.session_state:
        st.session_state.probe_results = []
    if "model_status" not in st.session_state:
        st.session_state.model_status = "Not checked"
    if "auto_selected" not in st.session_state:
        st.session_state.auto_selected = False

    # ── Auto-select on first load (no button press needed) ──
    if not st.session_state.auto_selected:
        st.session_state.auto_selected = True
        with st.spinner("🔍 Auto-detecting best models…"):
            primary, fallback, tertiary, results = auto_select_model(GEMINI_API_KEY)
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
            # Also populate the model list
            st.session_state.available_models = discover_models(GEMINI_API_KEY)

    # Manual re-probe buttons
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("🔍 Discover", use_container_width=True):
            with st.spinner("Scanning models…"):
                models = discover_models(GEMINI_API_KEY)
                st.session_state.available_models = models
                st.session_state.model_status = f"Found {len(models)} models"
    with btn_col2:
        if st.button("⚡ Re-probe", use_container_width=True):
            with st.spinner("Finding best models…"):
                primary, fallback, tertiary, results = auto_select_model(GEMINI_API_KEY)
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
                    st.session_state.model_status = "❌ No models available"
                if not st.session_state.available_models:
                    st.session_state.available_models = discover_models(GEMINI_API_KEY)

    # Model dropdown
    if st.session_state.available_models:
        model_ids = [m["id"] for m in st.session_state.available_models]
        model_labels = [get_model_display_label(m) for m in st.session_state.available_models]

        # Find current selection index
        current = st.session_state.selected_model
        default_idx = model_ids.index(current) if current in model_ids else 0

        chosen_label = st.selectbox(
            "Primary Model",
            model_labels,
            index=default_idx,
        )
        # Map label back to model ID
        chosen_idx = model_labels.index(chosen_label)
        st.session_state.selected_model = model_ids[chosen_idx]
    else:
        st.text_input(
            "Model ID",
            value=st.session_state.selected_model,
            key="manual_model_input",
            on_change=lambda: st.session_state.update(
                selected_model=st.session_state.manual_model_input
            ),
        )

    # Status display
    st.caption(f"🟢 Primary: **{st.session_state.selected_model}**")
    if st.session_state.fallback_model:
        st.caption(f"🟡 Fallback: **{st.session_state.fallback_model}**")
    if st.session_state.model_status != "Not checked":
        st.caption(f"Status: {st.session_state.model_status}")

    # Probe results (if any)
    if st.session_state.probe_results:
        with st.expander("📊 Probe Results", expanded=False):
            for r in st.session_state.probe_results:
                icon = "✅" if r["available"] else "❌"
                time_str = f"{r['response_time']}s"
                err = f" — {r['error']}" if r.get('error') else ""
                st.markdown(f"{icon} **{r['id']}** ({time_str}){err}")

    st.markdown("---")
    st.warning("🔒 Safety: Submit button is never clicked")
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


# ──────────────────────────────────────────────
#  CV Analysis (runs before the agent)
# ──────────────────────────────────────────────

def run_cv_analysis(cv_text: str):
    """Analyze the CV and generate a style profile. Returns (analysis, profile)."""
    llm = get_llm()
    # Build fallback LLM for CV analysis too
    fallback_model_id = st.session_state.get("fallback_model")
    fallback_llm = get_llm(fallback_model_id) if fallback_model_id else None

    with st.spinner("🧠 Analyzing CV — extracting skills, traits, and achievements…"):
        analysis = analyze_cv(cv_text, llm, fallback_llm=fallback_llm)

    with st.spinner("🎭 Building your communication persona…"):
        style_profile = generate_style_profile(analysis, llm, fallback_llm=fallback_llm)

    return analysis, style_profile


def display_analysis(analysis: dict, style_profile: str):
    """Show the CV analysis results in the Streamlit UI."""
    with st.expander("🧠 CV Analysis Results", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**Name:** {analysis.get('name', 'N/A')}")
            st.markdown(f"**Title:** {analysis.get('title', 'N/A')}")
            st.markdown(f"**Location:** {analysis.get('location', 'N/A')}")
            st.markdown(f"**Communication Style:** {analysis.get('communication_style', 'N/A')}")
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


# ──────────────────────────────────────────────
#  Agent
# ──────────────────────────────────────────────

def build_agent_prompt(cv_text: str, analysis: dict, style_profile: str) -> str:
    """Build the complete agent task prompt with persona and platform tips."""

    name = analysis.get("name", "the applicant")
    achievements = "\n".join(f"- {a}" for a in analysis.get("key_achievements", []))
    strengths = "\n".join(f"- {s}" for s in analysis.get("strengths", []))
    traits = ", ".join(analysis.get("personality_traits", []))
    technical = ", ".join(analysis.get("skills", {}).get("technical", []))
    soft = ", ".join(analysis.get("skills", {}).get("soft", []))

    edu_list = analysis.get("education", [])
    education = "; ".join(
        f"{e.get('degree', '')} from {e.get('institution', '')}"
        for e in edu_list
    ) if edu_list else "See CV"

    platform_tips = get_platform_tips()

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

# ──────────────────────────────────────────────
#  Form Handler JavaScript (Platform-Agnostic)
# ──────────────────────────────────────────────

YESNO_JS = """(function(){
    var results = [];
    var answer = 'No';

    function fireClick(el) {
        el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
        el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
        el.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        el.click();
    }

    // Strategy 1: role="radio" elements (standard ARIA)
    document.querySelectorAll('[role="radio"]').forEach(function(r) {
        if (r.textContent.trim() === answer && r.getAttribute('aria-checked') !== 'true') {
            fireClick(r);
            results.push('S1-radio: ' + r.textContent.trim());
        }
    });

    // Strategy 2: data-automation-id containing radio
    document.querySelectorAll('[data-automation-id*="radio"], [data-automation-id*="Radio"]').forEach(function(r) {
        if (r.textContent.trim() === answer && r.getAttribute('aria-checked') !== 'true') {
            fireClick(r);
            results.push('S2-auto: ' + r.textContent.trim());
        }
    });

    // Strategy 3: actual <input type="radio"> (may be hidden)
    document.querySelectorAll('input[type="radio"]').forEach(function(inp) {
        var label = inp.closest('label') || inp.parentElement;
        if (label && label.textContent.trim() === answer && !inp.checked) {
            inp.click();
            inp.checked = true;
            inp.dispatchEvent(new Event('change', {bubbles:true}));
            results.push('S3-input: ' + label.textContent.trim());
        }
    });

    // Strategy 4: any clickable element with exact text "No"
    if (results.length === 0) {
        var sel = 'button, [role="button"], [role="option"], div[tabindex], span[tabindex], label';
        document.querySelectorAll(sel).forEach(function(el) {
            if (el.textContent.trim() === answer) {
                fireClick(el);
                results.push('S4-generic: <' + el.tagName + '> ' + el.textContent.trim());
            }
        });
    }

    return results.length > 0
        ? 'YES/NO handled: ' + results.join('; ')
        : 'No Yes/No buttons found on this page.';
})()"""

VERIFY_FIELDS_JS = """(function(){
    try {
        var issues = [];

        // Check required fields that are empty
        document.querySelectorAll('input[required], textarea[required], select[required]').forEach(function(el) {
            try {
                if (!el.value || el.value.trim() === '') {
                    var label = el.getAttribute('aria-label')
                        || (el.labels && el.labels[0] ? el.labels[0].textContent.trim() : '')
                        || el.name || el.id || 'unknown';
                    issues.push('EMPTY REQUIRED: ' + label);
                }
            } catch(e) {}
        });

        // Check aria-required fields
        document.querySelectorAll('[aria-required="true"]').forEach(function(el) {
            try {
                var val = (el.value || el.textContent || '').trim();
                var tag = el.tagName.toLowerCase();
                // Skip if it's a container or already has content
                if (tag === 'div' || tag === 'span' || tag === 'fieldset') return;
                if (val === '' || val === 'Select One') {
                    var label = el.getAttribute('aria-label') || el.id || 'unknown';
                    issues.push('ARIA REQUIRED UNFILLED: ' + label);
                }
            } catch(e) {}
        });

        // Check unchecked radio groups
        var radioGroups = {};
        document.querySelectorAll('[role="radio"]').forEach(function(r) {
            try {
                var group = r.closest('[role="radiogroup"]') || r.parentElement;
                var gid = group ? (group.id || group.getAttribute('data-automation-id') || 'group') : 'ungrouped';
                if (!radioGroups[gid]) radioGroups[gid] = {any_checked: false, label: ''};
                if (r.getAttribute('aria-checked') === 'true') radioGroups[gid].any_checked = true;
                if (!radioGroups[gid].label) radioGroups[gid].label = (group ? group.textContent.substring(0,40).trim() : gid);
            } catch(e) {}
        });
        for (var gid in radioGroups) {
            if (!radioGroups[gid].any_checked) {
                issues.push('UNCHECKED RADIO GROUP: ' + radioGroups[gid].label);
            }
        }

        // Check for visible error messages
        document.querySelectorAll('[class*="error"], [class*="Error"], [role="alert"], [data-automation-id*="error"]').forEach(function(el) {
            try {
                var text = (el.textContent || '').trim();
                if (text && text.length > 2 && text.length < 200 && el.offsetParent !== null) {
                    issues.push('ERROR MSG: ' + text.substring(0, 80));
                }
            } catch(e) {}
        });

        return issues.length > 0
            ? 'VERIFICATION FAILED — ' + issues.length + ' issues:\\n' + issues.join('\\n')
            : 'VERIFICATION PASSED — all fields filled, no errors detected.';
    } catch(e) {
        return 'VERIFICATION PASSED — (script fallback, check manually)';
    }
})()"""


async def run_agent(url: str, cv_text: str, analysis: dict,
                    style_profile: str, cv_file_path: str | None = None):
    """Launch the browser agent to fill a job application form."""

    # Resolve local file:// URLs via HTTP server
    if url.startswith("file:///"):
        raw = url.replace("file:///", "")
        start_local_server(os.path.dirname(raw))
        url = f"http://127.0.0.1:8000/{os.path.basename(raw)}"
        st.info(f"📁 Serving local file at {url}")

    # LLM — primary + fallback for mid-session recovery
    llm = get_agent_llm()
    fallback_model_id = st.session_state.get("fallback_model")
    fallback_llm = get_agent_llm(fallback_model_id) if fallback_model_id else None

    # ── Persistent Logger ──
    logger = AgentLogger(
        url=url,
        model_id=st.session_state.get("selected_model", DEFAULT_MODEL),
        fallback_model_id=fallback_model_id,
    )
    st.caption(f"📝 Logging to: `{logger.filepath}`")

    # Build the enhanced prompt
    task = build_agent_prompt(cv_text, analysis, style_profile)

    # Append the Yes/No handler JS (runs on ALL platforms, not just Workday)
    task += (
        "\n\n⚠️ YES/NO HANDLER JS — use this with the `evaluate` action "
        "on EVERY page AFTER filling text fields but BEFORE clicking Next:\n" + YESNO_JS
    )

    # Append the verification JS (mandatory pre-Next gate)
    task += (
        "\n\n✅ VERIFICATION JS — you MUST run this with `evaluate` BEFORE "
        "clicking Next on EVERY page. If it reports issues, fix them first:\n" + VERIFY_FIELDS_JS
    )

    # Tell the agent about the CV file for uploading
    file_paths = []
    if cv_file_path:
        file_paths.append(cv_file_path)
        task += (
            f"\n\n📎 CV FILE FOR UPLOAD: {cv_file_path}\n"
            "When you see a Resume/CV upload field, use the upload_file action "
            "with this file path. This is the applicant's CV/resume file."
        )

    # Log CV analysis completion
    logger.log_event("cv_analysis_done", {"name": analysis.get("name", "unknown")})

    # Callback — logs every step + throttles API calls
    async def on_step(state, output, step_num):
        try:
            # Extract page URL from browser state
            page_url = getattr(state, "url", "") if state else ""

            # Persistent log
            logger.log_step(step_num, output, page_url)

            # Streamlit UI log
            with log_container:
                with st.chat_message("assistant"):
                    st.write(f"**Step {step_num}**")
                    goal = getattr(output, "next_goal", None) or getattr(output, "thinking", "…")
                    st.code(goal, language="text")

            await asyncio.sleep(10)
        except Exception as e:
            logger.log_error(str(e), context=f"step_callback_{step_num}")

    # Browser + Agent
    browser = Browser(
        browser_profile=BrowserProfile(
            headless=False,
            keep_alive=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
    )

    # Build initial actions — Yes/No + page load on ALL sites
    initial_acts = [
        {"navigate": {"url": url}},
        {"wait": {"seconds": 5}},
        {"evaluate": {"code": YESNO_JS}},
    ]

    agent = Agent(
        task=task,
        llm=llm,
        fallback_llm=fallback_llm,  # browser-use auto-switches on 429/503
        browser=browser,
        register_new_step_callback=on_step,
        use_vision=False,
        initial_actions=initial_acts,
        available_file_paths=file_paths if file_paths else None,
        max_actions_per_step=10,
        max_failures=5,
    )

    with st.spinner("🚀 Agent is filling the form…"):
        try:
            await agent.run()
        except Exception as e:
            logger.log_error(str(e), context="agent_run")
            st.error(f"❌ Agent stopped: {e}")

    # Show run summary
    run_summary = logger.summary()
    st.success("✅ Done! Review the form and submit manually.")
    with st.expander("📊 Run Summary", expanded=True):
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Steps", run_summary["total_steps"])
        col_b.metric("Errors", run_summary["total_errors"])
        col_c.metric("Pages", run_summary["pages_visited"])
        st.caption(f"⏱️ Duration: {run_summary['elapsed_human']}")
        st.caption(f"📝 Full log: `{run_summary['log_file']}`")
    st.balloons()


# ──────────────────────────────────────────────
#  Launch
# ──────────────────────────────────────────────

if st.button("🚀 Start Agent", type="primary"):
    # Resolve CV text and save file for upload
    cv_text = ""
    cv_file_path = None  # Absolute path for the agent to upload
    if cv_upload:
        # Save the uploaded file to a temp location for the agent
        suffix = ".pdf" if cv_upload.type == "application/pdf" else ".txt"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix,
                                          prefix="cv_", dir=tempfile.gettempdir())
        tmp.write(cv_upload.getvalue())
        tmp.close()
        cv_file_path = tmp.name
        st.info(f"📎 CV saved for upload: {cv_file_path}")

        if cv_upload.type == "application/pdf":
            cv_text = extract_pdf_text(cv_upload) or ""
            if not cv_text:
                st.error("Could not read PDF.")
                st.stop()
        else:
            cv_text = cv_upload.getvalue().decode("utf-8")
    else:
        cv_path_local = os.environ.get("RESUMEFILL_CV_PATH", "")
        cv_text = (read_file(cv_path_local) or "") if cv_path_local else ""
        if cv_text:
            st.info("Using the externally configured CV file.")
            cv_file_path = os.path.abspath(cv_path_local)
        else:
            st.error("Upload a CV or set RESUMEFILL_CV_PATH to a file outside this repository.")
            st.stop()

    if not target_url:
        st.error("Enter a job application URL.")
        st.stop()

    # Step 1: Analyze CV and build persona
    analysis, style_profile = run_cv_analysis(cv_text)
    display_analysis(analysis, style_profile)

    # Step 2: Run the agent with persona-enhanced prompts
    asyncio.run(run_agent(target_url, cv_text, analysis, style_profile,
                          cv_file_path=cv_file_path))
