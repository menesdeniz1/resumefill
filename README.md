# ResumeFill — supervised application-form experiment

A Python/Streamlit prototype that uses Google Gemini and browser-use to interpret a supplied CV and assist with filling application forms. It is an experiment in model-guided browser interaction, not a reliable autonomous job-application service.

## Components

- `main.py`: local UI, PDF/text intake and browser-agent orchestration.
- `cv_analyzer.py`: model-assisted CV interpretation and response-style generation.
- `model_selector.py`: provider model discovery and selection.
- `agent_logger.py`: local operation logs.
- `cv.example.txt`: synthetic example only; no real CV is included.

## Local setup

Create a Python 3.11+ virtual environment, then:

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m streamlit run main.py
```

Configure `GEMINI_API_KEY` locally, never in committed files. Upload a PDF/TXT or set `RESUMEFILL_CV_PATH` to a file outside this repository. Optional `RESUMEFILL_LOG_DIR` must also point outside the checkout; its default is `~/.local/share/resumefill/logs`. Dependencies are not locked, so upstream API changes may require adjustments.

## Safety boundaries

The agent is **prompted** not to submit applications. This is not a technical submission lock and cannot guarantee that a model-controlled browser will never click Submit. Supervise every action and initially use synthetic data on local test forms. Do not run unattended against real employers or assume a draft will remain unsent.

CV text, derived responses and page content may be sent to configured AI providers and entered into websites. Review provider policies and generated answers. Model inferences about personality or experience are not verified facts; do not use invented qualifications or accomplishments.

Platform-specific prompt guidance exists, but compatibility with Workday, Lever, Greenhouse or LinkedIn is **not certified**. Respect site rules. No real applications or live provider calls were performed during publication review; no end-to-end success rate is claimed.

## Maintenance

Personal CVs and application logs were removed from reachable branches. Old external clones and cached GitHub commits are not erased by this cleanup. Use main: historical development branches may not include the newest path guards. See [maintenance notes](PUBLICATION_NOTES.md). Do not commit your CV, API keys, browser sessions or generated logs.
