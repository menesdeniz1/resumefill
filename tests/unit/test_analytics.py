"""Analytics aggregation over run logs."""

import json

from resumefill.analytics import aggregate_runs


def _write_run(path, *, url, model="gemini-flash-latest", success=True,
               steps=10, errors=0, elapsed_s=42.5, complete=True):
    lines = [
        {"type": "event", "event": "run_start",
         "data": {"url": url, "primary_model": model, "fallback_model": None}},
    ]
    if steps:
        for i in range(1, steps + 1):
            lines.append({"type": "step", "step": i, "page_url": url})
    if errors:
        lines.append({"type": "error", "message": "boom", "context": "test"})
        lines.append({"type": "event", "event": "quota_error"})
    if complete:
        lines.append({
            "type": "event", "event": "run_complete",
            "data": {"success": success, "total_steps": steps, "total_errors": errors,
                     "elapsed_seconds": elapsed_s, "elapsed_human": "0m 42s"},
        })
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def test_aggregate_counts_success_and_platform(tmp_path):
    _write_run(tmp_path / "a.jsonl",
               url="https://ing.wd3.myworkdayjobs.com/job/x")
    _write_run(tmp_path / "b.jsonl",
               url="https://jobs.lever.co/acme/1", success=False, errors=2)
    # Legacy log: completed but no recorded success flag.
    _write_run(tmp_path / "c.jsonl",
               url="https://boards.greenhouse.io/acme/2", success=None)

    stats = aggregate_runs(tmp_path)
    assert stats["total_runs"] == 3
    assert stats["successful_runs"] == 1
    assert stats["failed_runs"] == 1
    assert stats["success_rate"] is not None and 0 < stats["success_rate"] <= 1
    assert stats["total_errors"] == 2  # authoritative value from run_complete summary
    by_platform = stats["by_platform"]
    assert by_platform["workday"]["runs"] == 1
    assert by_platform["lever"]["runs"] == 1
    assert by_platform["greenhouse"]["successful"] == 0  # unknown ≠ success


def test_incomplete_and_corrupt_files_are_skipped(tmp_path):
    _write_run(tmp_path / "good.jsonl", url="https://jobs.lever.co/a/1")
    (tmp_path / "truncated.jsonl").write_text(
        json.dumps({"type": "event", "event": "run_start",
                    "data": {"url": "https://x.com"}}) + "\n", encoding="utf-8")
    (tmp_path / "garbage.jsonl").write_text("not json at all\n", encoding="utf-8")

    stats = aggregate_runs(tmp_path)
    assert stats["total_runs"] == 1
    assert stats["skipped_files"] == 2


def test_recent_sorted_newest_first_and_rows(tmp_path):
    import json as j

    base = [
        ("2026-01-01T10:00:00Z", tmp_path / "old.jsonl"),
        ("2026-02-02T11:00:00Z", tmp_path / "new.jsonl"),
    ]
    for ts, path in base:
        _write_run(path, url="https://jobs.lever.co/a/1")
        # rewrite first line's timestamp to control ordering deterministically
        content = path.read_text(encoding="utf-8").splitlines()
        record = j.loads(content[0])
        record["timestamp"] = ts
        content[0] = j.dumps(record)
        path.write_text("\n".join(content) + "\n", encoding="utf-8")

    stats = aggregate_runs(tmp_path)
    assert [r.file for r in stats["recent"]] == ["new.jsonl", "old.jsonl"]
    row = stats["recent"][0].as_row()
    assert row["Outcome"] == "✅"
    assert row["Platform"] == "lever"
    assert row["Duration"] == "0m 42s"


def test_empty_dir_yields_zeroed_stats(tmp_path):
    stats = aggregate_runs(tmp_path / "missing")
    assert stats["total_runs"] == 0
    assert stats["avg_steps"] is None
    assert stats["success_rate"] is None
    assert stats["by_platform"] == {}
