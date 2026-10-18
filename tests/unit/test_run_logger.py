import json
from types import SimpleNamespace

from resumefill.logging_utils.run_logger import AgentLogger


class FakeAction:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self, exclude_unset=True):
        return self._payload


def _make_logger(tmp_path):
    return AgentLogger(
        url="https://ing.wd3.myworkdayjobs.com/job/x",
        model_id="gemini-flash-latest",
        fallback_model_id="gemini-2.5-flash",
        log_dir=tmp_path,
    )


def test_log_file_created_with_header(tmp_path):
    logger = _make_logger(tmp_path)
    lines = logger.filepath.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    header = json.loads(lines[0])
    assert header["event"] == "run_start"
    assert header["data"]["primary_model"] == "gemini-flash-latest"
    assert "wd3-myworkdayjobs-com" in logger.filepath.name


def test_log_step_records_actions_and_pages(tmp_path):
    logger = _make_logger(tmp_path)
    output = SimpleNamespace(
        thinking="t",
        evaluation_previous_goal="ok",
        memory="m",
        next_goal="g",
        action=[FakeAction({"click": {"index": 1}, "wait": None})],
    )
    logger.log_step(1, output, "https://a.example/1")
    logger.log_step(2, output, "https://a.example/1")  # same page — deduped
    logger.log_step(3, output, "https://a.example/2")

    summary = logger.summary()
    assert summary["total_steps"] == 3
    assert summary["pages_visited"] == 2
    assert summary["total_errors"] == 0

    steps = [
        json.loads(line)
        for line in logger.filepath.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["type"] == "step"
    ]
    assert steps[0]["actions"] == ["click"]
    assert all("timestamp" in s for s in steps)


def test_errors_and_events_counted(tmp_path):
    logger = _make_logger(tmp_path)
    logger.log_event("quota_error", {"code": 429})
    logger.log_error("boom", context="test")
    summary = logger.summary()
    assert summary["total_errors"] == 2
    complete = [
        json.loads(line)
        for line in logger.filepath.read_text(encoding="utf-8").splitlines()
    ][-1]
    assert complete["event"] == "run_complete"


def test_field_filled_event_logged_for_typed_values(tmp_path):
    """P5 harvest: typed field values land in the JSONL for the memory bank."""
    logger = _make_logger(tmp_path)
    output = SimpleNamespace(
        thinking="t",
        evaluation_previous_goal="ok",
        memory="m",
        next_goal="g",
        action=[
            FakeAction({"input_text": {"index": 3, "text": "Mücahid Deniz"}}),
            FakeAction({"send_keys": {"keys": "Tab"}}),  # no user-facing value
            FakeAction({"click": {"index": 1}}),
        ],
    )
    logger.log_step(1, output, "https://a.example/1")

    events = [
        json.loads(line)
        for line in logger.filepath.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("event") == "field_filled"
    ]
    assert len(events) == 1
    assert events[0]["action"] == "input_text"
    assert events[0]["text"] == "Mücahid Deniz"
    assert "timestamp" in events[0]


def test_field_filled_truncates_long_values(tmp_path):
    logger = _make_logger(tmp_path)
    long_value = "x" * 500
    output = SimpleNamespace(
        thinking="t",
        evaluation_previous_goal="ok",
        memory="m",
        next_goal="g",
        action=[FakeAction({"input_text": {"index": 2, "text": long_value}})],
    )
    logger.log_step(1, output, "https://a.example/1")
    events = [
        json.loads(line)
        for line in logger.filepath.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("event") == "field_filled"
    ]
    assert events[0]["text"] == "x" * 300


def test_field_filled_covers_dropdown_and_upload(tmp_path):
    logger = _make_logger(tmp_path)
    output = SimpleNamespace(
        thinking="t",
        evaluation_previous_goal="ok",
        memory="m",
        next_goal="g",
        action=[
            FakeAction({"select_dropdown_option": {"index": 4, "text": "Turkey"}}),
            FakeAction({"upload_file": {"index": 7, "path": "cv.pdf"}}),
        ],
    )
    logger.log_step(2, output, "https://a.example/1")
    events = [
        json.loads(line)
        for line in logger.filepath.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("event") == "field_filled"
    ]
    assert [e["text"] for e in events if "text" in e] == ["Turkey"]
    assert [e["path"] for e in events if "path" in e] == ["cv.pdf"]
