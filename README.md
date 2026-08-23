# 🤖 resumefill — Job Application Agent

An autonomous browser agent that fills out job application forms using your CV.
It analyzes your CV once, builds a communication persona, then answers
open-ended questions **in your voice** while filling structured fields from
your data — powered by **Google Gemini** and **browser-use**.

> Personal-use software: the agent fills forms on your behalf and **never
> submits them** — submission blocking is enforced in code, not just prompted.

---

## How It Works

```
CV (PDF/TXT) ──▶ CV Analyzer ──▶ Persona ──▶ Browser Agent ──▶ Filled form
                    │                          (Gemini + browser-use)
             structured profile          guarded click action:
             skills · traits ·           submit controls are blocked
             achievements                in Python, not just prompted
```

1. You provide a job application URL and your CV.
2. The analyzer extracts a structured profile and generates a persona that
   captures how *you* write.
3. The agent opens a real browser, reads the form, fills fields, and answers
   open-ended questions following the persona.
4. Before every page advance it runs an injected verification script; the
   final Submit button is unreachable by design.

## Project Layout

```
src/resumefill/
├── config.py            # env-driven settings (single source of truth)
├── text_utils.py        # unicode/mojibake sanitization for CV text
├── model_selection.py   # bounded Gemini discovery/probing/auto-selection
├── platforms.py         # platform detection (Workday/Lever/…) + scoped tips
├── cv/
│   ├── extract.py       # TXT/PDF text extraction with quality warnings
│   └── analyzer.py      # profile extraction + persona generation
├── llm/factory.py       # unified LLM construction for both back-ends
├── agent/
│   ├── scripts.py       # YESNO / VERIFY JavaScript injected via evaluate
│   ├── prompts.py       # task-prompt assembly (pure functions)
│   ├── safety.py        # submit-element classification (pure)
│   ├── tools.py         # GuardedTools: code-level submit blocking
│   └── service.py       # JobFormAgent orchestration + local file server
├── logging_utils/       # JSONL run logger
└── ui/app.py            # Streamlit interface (thin layer)

tests/
├── unit/                # 70+ fast tests (no network/browser needed)
└── integration/         # playwright tests against fixture form pages

data/cv.txt              # fallback CV used when nothing is uploaded
```

## Setup

**Prerequisites:** Python 3.11+, a free Gemini API key
([aistudio.google.com/apikey](https://aistudio.google.com/apikey)).

```bash
# create venv (recommended)
python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # Linux/macOS

pip install -e ".[dev]"
playwright install chromium
```

Configure the API key — copy `.env.example` to `.env`:

```
GEMINI_API_KEY=your_key_here
```

Optional `RF_*` variables override defaults (`max_steps`, `headless`, …) —
see `.env.example`.

## Usage

```bash
python -m resumefill
# or: streamlit run src/resumefill/ui/app.py
```

1. Paste the job application URL (Workday, Lever, Greenhouse, LinkedIn or
   any generic site).
2. Upload your CV (PDF/TXT) or rely on `data/cv.txt`.
3. Click **🚀 Start Agent**, watch progress live, review the filled form,
   and submit manually.

Run logs land in `logs/*.jsonl` (git-ignored — they contain personal data).

## Safety Model

| Layer | Mechanism |
|-------|-----------|
| Code | `GuardedTools` intercepts every click; submit-like elements are refused |
| Prompt | Explicit "never click Submit" rule as second line of defence |
| Verification | Mandatory JS gate before advancing pages |
| Telemetry | Disabled by default (`ANONYMIZED_TELEMETRY=false`) |

Known limitation (documented in `agent/tools.py`): Enter-in-single-line-input
submissions are not intercepted because Enter is legitimate inside
textareas.

## Development

```bash
pytest                 # everything
pytest -m "not browser"  # fast unit suite
pytest -m "browser"      # JS integration (needs chromium)
ruff check src tests     # lint
```

CI runs lint, unit tests, and the browser integration suite separately
(`.github/workflows/ci.yml`). Bug fixes should come with regression tests;
the integration fixtures double as minimal reproductions of job-board DOMs.

## License

For personal use. Use responsibly and in compliance with the terms of
service of the sites you apply through.
