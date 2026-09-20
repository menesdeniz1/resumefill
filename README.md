# Current maintenance status

Real CV data and application logs were removed from reachable history. cv.example.txt is synthetic. Upload your own CV or set RESUMEFILL_CV_PATH to an external file. Logs default outside the repo (RESUMEFILL_LOG_DIR). This agent can send CV data to configured AI providers and interact with job sites; no real applications were submitted or end-to-end automation validated during cleanup.

See [PUBLICATION_NOTES.md](PUBLICATION_NOTES.md).

---

# 🤖 Job Application Agent

An autonomous browser agent that fills out job application forms using your CV data. It **automatically analyzes your CV** to understand your personality, strengths, and communication style — then answers open-ended questions **in your personal voice**.

Powered by **Google Gemini Flash** and **browser-use** for intelligent, real-time form automation.

---

## How It Works

```
┌──────────┐      ┌──────────────┐      ┌──────────────┐      ┌─────────────┐
│  Your CV │ ───▶ │ CV Analyzer  │ ───▶ │ Gemini Flash │ ───▶ │  Browser    │
│ (PDF/TXT)│      │ (Persona AI) │      │ (Form Agent) │      │  Automation │
└──────────┘      └──────────────┘      └──────────────┘      └─────────────┘
                        │                       │
                  Extracts skills,        Fills fields +
                  traits, persona         answers questions
                  from your CV            in YOUR style
```

1. **You provide** a job application URL and your CV (PDF or TXT).
2. **The CV Analyzer** reads your CV and extracts skills, achievements, personality traits, and communication style.
3. **A persona is generated** — a description of how YOU write and communicate.
4. **The agent** opens a real browser, navigates to the page, reads the form fields.
5. **Gemini Flash** fills structured fields from your CV AND answers open-ended questions in your personal style.
6. **You review** the filled form and submit manually. The agent never clicks Submit.

---

## Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| **Workday** | ✅ Supported | Radio button handling, address formatting |
| **Lever** | ✅ Supported | Simple forms, custom text questions |
| **Greenhouse** | ✅ Supported | Multi-page forms, demographic questions |
| **LinkedIn Easy Apply** | ✅ Supported | 2-3 step forms, fit questions |

---

## Project Structure

```
Bot/
├── main.py            # Streamlit UI + Agent (with CV analysis integration)
├── cv_analyzer.py     # CV analysis engine (persona & style extraction)
├── cv.txt             # Default CV data (used if no file uploaded)
├── requirements.txt   # Python dependencies
├── .env               # API key (not committed to git)
├── .gitignore         # Git ignore rules
└── README.md          # This file
```

### File Details

| File | Purpose |
|------|---------|
| `main.py` | Streamlit UI + agent logic. Runs CV analysis before launching the browser agent. Builds a persona-enhanced prompt. |
| `cv_analyzer.py` | Standalone CV analysis module. Extracts structured data, generates a communication persona, and provides personalized Q&A. |
| `cv.txt` | Fallback CV in plain text. Used automatically when no PDF/TXT is uploaded. Replace with your own CV data. |

---

## Setup

### Prerequisites

- **Python 3.11+**
- **Google Gemini API key** — free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### Installation

```bash
# Clone or download the project
cd Bot

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers (first time only)
playwright install chromium
```

### API Key Configuration

Set your Gemini API key using **one** of these methods:

**Option A — `.env` file (recommended):**
Create a `.env` file in the project root:
```
GEMINI_API_KEY=your_key_here
```

**Option B — Environment variable:**
```bash
set GEMINI_API_KEY=your_key_here     # Windows CMD
$env:GEMINI_API_KEY="your_key_here"  # PowerShell
export GEMINI_API_KEY=your_key_here  # Linux/Mac
```

---

## Usage

### Start the Application

```bash
python -m streamlit run main.py
```

This opens a web UI at `http://localhost:8501`.

### Fill a Real Job Application

1. Paste the job application URL (e.g., Workday, Lever, Greenhouse, LinkedIn)
2. Upload your CV (PDF or TXT) — or place a `cv.txt` file in the project folder
3. Click **🚀 Start Agent**
4. The system first **analyzes your CV** and shows:
   - Extracted personality traits and strengths
   - Generated communication persona
5. The agent then fills the form in real-time using your persona
6. Review the filled form and submit manually

---

## Architecture

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM** | Google Gemini 2.0 Flash | CV analysis, persona generation, form filling |
| **CV Analysis** | Custom prompts + Gemini | Extracts structured data and communication style |
| **Browser Automation** | browser-use + Playwright | Controls a real Chromium browser |
| **UI** | Streamlit | Web interface for configuration and monitoring |
| **CV Parsing** | pypdf | Extracts text from PDF resumes |

### Agent Loop

```
1. Analyze CV → Extract skills, traits, achievements
2. Generate persona → How this person communicates
3. Read current page state (DOM tree with interactive elements)
4. Send state + CV + persona + task prompt to Gemini
5. Gemini returns action(s): click, type, select dropdown, etc.
6. Execute action(s) in the browser
7. Repeat until all fields are filled
```

### CV Analyzer Pipeline

```
CV Text → analyze_cv() → Structured Profile (JSON)
                              ↓
                    generate_style_profile() → Persona Description
                              ↓
                    build_agent_prompt() → Enhanced Agent Task
```

The analyzer extracts:
- **Contact info**: name, email, phone, location
- **Skills**: technical, tools, soft skills
- **Achievements**: quantified accomplishments
- **Personality traits**: inferred from experience
- **Communication style**: tone, structure, vocabulary
- **Strengths**: unique differentiators

### Safety

- The agent **never clicks Submit**. You always review first.
- A real Chrome User-Agent is used to avoid bot detection.
- The browser runs in visible mode (not headless) so you can watch every action.
- `keep_alive=True` prevents the browser from closing unexpectedly.

---

## Configuration

Key settings in `main.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model variant |
| `temperature` | `0.3` | Lower = more deterministic responses |
| `max_actions_per_step` | `10` | Max browser actions per LLM call |
| `max_failures` | `5` | Retries before the agent stops |
| `headless` | `False` | Set `True` to run browser invisibly |
| `keep_alive` | `True` | Keeps browser open between steps |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `playwright` not found | Run `playwright install chromium` |
| API key error | Check `GEMINI_API_KEY` is set in `.env` |
| `file://` URL blocked | The agent auto-converts to `http://localhost:8000` |
| Agent clicks Submit | Already prevented by default in the prompt |
| Form fields not detected | Complex sites with shadow DOM may need adjustments |
| Generic-sounding answers | Check the persona in the "Generated Persona" expander |
| Slow CV analysis | First run takes ~5-10s for CV analysis; this is normal |

---

## License

This project is for personal use. Use responsibly and in compliance with job application site terms of service.
