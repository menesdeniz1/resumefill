
import json

from resumefill.agent.prompts import format_education
from resumefill.agent.service import (
    _log_form_state,
    _maybe_convert_file_url,
)
from resumefill.config import Settings
from resumefill.platforms import detect_platform


def test_settings_defaults_and_api_key_flag(tmp_path):
    settings = Settings(gemini_api_key="", log_dir=tmp_path, data_dir=tmp_path)
    assert not settings.has_api_key
    filled = Settings(gemini_api_key="k", log_dir=tmp_path, data_dir=tmp_path)
    assert filled.has_api_key


def test_default_cv_path_prefers_data_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    assert Settings(data_dir=data).default_cv_path() is None

    (data / "cv.txt").write_text("x", encoding="utf-8")
    path = Settings(data_dir=data).default_cv_path()
    assert path == data / "cv.txt"


def test_format_education_skips_empty_pieces():
    analysis = {"education": [{"institution": "BAU", "degree": ""}]}
    assert format_education(analysis) == "BAU"


def test_build_task_includes_preapproved_answers(settings):
    from resumefill.agent.service import JobFormAgent

    agent = JobFormAgent(settings)
    task = agent.build_task(
        "https://jobs.lever.co/acme/1",
        cv_text="CV",
        analysis={"name": "T"},
        style_profile="persona",
        pre_approved_answers={"about_you": "I ship AOI systems."},
    )
    assert "PRE-APPROVED ANSWERS" in task
    assert "I ship AOI systems." in task

    plain = agent.build_task(
        "https://jobs.lever.co/acme/1", cv_text="CV", analysis={}, style_profile="p"
    )
    assert "PRE-APPROVED ANSWERS" not in plain


def test_build_task_embeds_job_description_when_given(settings):
    from resumefill.agent.service import JobFormAgent

    agent = JobFormAgent(settings)
    with_jd = agent.build_task(
        "https://jobs.lever.co/acme/1",
        cv_text="CV",
        analysis={"name": "T"},
        style_profile="p",
        job_description="GenAI Data Analyst — ING, Istanbul",
    )
    assert "JOB DESCRIPTION" in with_jd
    assert "GenAI Data Analyst — ING, Istanbul" in with_jd

    without_jd = agent.build_task(
        "https://jobs.lever.co/acme/1", cv_text="CV", analysis={}, style_profile="p",
        job_description="   ",
    )
    assert "JOB DESCRIPTION" not in without_jd


def test_local_file_server_serves_files(tmp_path):
    (tmp_path / "form.html").write_text("<html>hi</html>", encoding="utf-8")
    url = f"file:///{(tmp_path / 'form.html').as_posix()}"

    resolved, server = _maybe_convert_file_url(url)
    assert server is not None
    with server:
        import urllib.request

        with urllib.request.urlopen(resolved) as response:
            body = response.read().decode("utf-8")
            assert "hi" in body


def test_http_urls_pass_through():
    resolved, server = _maybe_convert_file_url("https://jobs.example.com/apply")
    assert resolved == "https://jobs.example.com/apply"
    assert server is None


def test_detect_platform_smoke():
    assert detect_platform("https://x.wd3.myworkdayjobs.com/a").value == "workday"


# --- P5-1: form-state harvest snapshot -------------------------------------


class _FakePage:
    def __init__(self, raw):
        self._raw = raw

    async def evaluate(self, script):
        assert script.strip().startswith("("), "browser_use requires arrow-function form"
        return self._raw


class _FakeBrowser:
    def __init__(self, raw):
        self.page = _FakePage(raw)

    async def get_current_page(self):
        return self.page


def _logger_for(tmp_path):
    from resumefill.logging_utils.run_logger import AgentLogger

    return AgentLogger(
        url="https://example.com/job/x",
        model_id="m",
        fallback_model_id=None,
        log_dir=tmp_path,
    )


def _events(tmp_path, name):
    return [
        json.loads(line)
        for file in tmp_path.glob("*.jsonl")
        for line in file.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("event") == name
    ]


async def test_form_state_snapshot_logged(tmp_path):
    payload = '{"fields": [{"label": "Full Name", "type": "text", "value": "M. Deniz"}]}'
    logger = _logger_for(tmp_path)
    await _log_form_state(_FakeBrowser(payload), logger)
    events = _events(tmp_path, "form_state")
    assert len(events) == 1
    assert events[0]["data"]["fields"][0]["label"] == "Full Name"


async def test_form_state_tolerates_double_encoded_json(tmp_path):
    payload = json.dumps(json.dumps({"fields": [{"label": "Email", "type": "text", "value": "a@b.c"}]}))
    logger = _logger_for(tmp_path)
    await _log_form_state(_FakeBrowser(payload), logger)
    assert _events(tmp_path, "form_state")[0]["data"]["fields"][0]["value"] == "a@b.c"


async def test_form_state_missing_page_is_silent(tmp_path):
    class _NoPage:
        async def get_current_page(self):
            return None

    logger = _logger_for(tmp_path)
    await _log_form_state(_NoPage(), logger)
    assert _events(tmp_path, "form_state") == []


async def test_form_state_evaluate_failure_is_silent(tmp_path):
    class _BrokenPage:
        async def evaluate(self, script):
            raise RuntimeError("context destroyed")

    class _BrokenBrowser:
        async def get_current_page(self):
            return _BrokenPage()

    logger = _logger_for(tmp_path)
    await _log_form_state(_BrokenBrowser(), logger)
    assert _events(tmp_path, "form_state") == []
    assert logger.filepath.exists()
