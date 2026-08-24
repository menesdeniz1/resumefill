"""Outcome store: funnel tracking with latest-wins semantics."""

import json

import pytest

from resumefill.outcomes import OutcomeStatus, OutcomeStore


@pytest.fixture
def store(tmp_path):
    return OutcomeStore(tmp_path / "data")


def test_record_requires_url(store):
    with pytest.raises(ValueError):
        store.record("", "applied")
    with pytest.raises(ValueError):
        store.record("   ", "applied")


def test_record_rejects_invalid_status(store):
    with pytest.raises(ValueError):
        store.record("https://jobs.lever.co/a/1", "hired-forever")


def test_record_and_latest_wins(store):
    store.record("https://jobs.lever.co/a/1", "applied")
    store.record("https://jobs.lever.co/a/1", "interview", notes="phone screen")
    latest = store.latest_by_url()
    assert len(latest) == 1
    assert latest["https://jobs.lever.co/a/1"].status is OutcomeStatus.INTERVIEW
    # History preserved: both records on disk.
    assert len(store.all()) == 2


def test_platform_detected_from_url(store):
    outcome = store.record("https://ing.wd3.myworkdayjobs.com/job/x", "applied")
    assert outcome.platform == "workday"


def test_aggregate_counts_latest_only(store):
    store.record("https://jobs.lever.co/a/1", "applied")
    store.record("https://jobs.lever.co/a/1", "interview")  # supersedes applied
    store.record("https://boards.greenhouse.io/b/2", "rejected")
    agg = store.aggregate()

    assert agg["total_urls"] == 2
    assert agg["by_status"]["applied"] == 0  # superseded — snapshot, not cumulative
    assert agg["by_status"]["interview"] == 1
    assert agg["by_status"]["rejected"] == 1
    assert agg["by_platform"]["lever"] == {"urls": 1, "advanced": 1}
    assert agg["by_platform"]["greenhouse"] == {"urls": 1, "advanced": 0}
    assert agg["advance_rate"] == pytest.approx(0.5)


def test_empty_store_zeroed_aggregate(tmp_path):
    agg = OutcomeStore(tmp_path / "none").aggregate()
    assert agg["total_urls"] == 0
    assert agg["advance_rate"] is None
    assert all(v == 0 for v in agg["by_status"].values())


def test_corrupt_lines_skipped(store):
    store.record("https://jobs.lever.co/a/1", "applied")
    with open(store.path, "a", encoding="utf-8") as f:
        f.write("{broken json\n")
    store.record("https://jobs.lever.co/b/2", "offer")
    agg = store.aggregate()
    assert agg["total_urls"] == 2
    assert agg["by_status"]["offer"] == 1


def test_jsonl_is_utf8_with_trailing_newline(store):
    store.record("https://jobs.lever.co/ünïcode/1", "applied")
    raw = store.path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    record = json.loads(raw)
    assert record["url"].startswith("https://jobs.lever.co/")
