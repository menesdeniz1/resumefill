
from resumefill.agent.prompts import format_education
from resumefill.agent.service import (
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
