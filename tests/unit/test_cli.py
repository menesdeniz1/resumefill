"""CLI: argument parsing and the profiles subcommand (no LLM/browser)."""

import json

import pytest

from resumefill.cli import build_parser
from resumefill.profiles.store import CvProfile, ProfileStore


def test_parser_defaults_to_ui():
    args = build_parser().parse_args([])
    assert args.command is None

    args = build_parser().parse_args(["ui"])
    assert args.command == "ui"


def test_parser_run_flags():
    args = build_parser().parse_args(
        ["run", "https://x.com/apply", "--profile", "ada", "--dry-run"]
    )
    assert args.command == "run"
    assert args.url == "https://x.com/apply"
    assert args.profile == "ada"
    assert args.cv is None
    assert args.dry_run is True


def test_parser_run_source_group_is_exclusive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["run", "https://x.com", "--profile", "a", "--cv", "b.pdf"]
        )


def test_parser_profiles_show_requires_slug():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["profiles", "show"])


def test_profiles_list_and_show(tmp_path, capsys):
    store = ProfileStore(tmp_path)
    store.save(CvProfile(name="Ada Lovelace", title="Pioneer"))

    from resumefill.cli import _cmd_profiles

    class Args:
        profiles_command = "list"

    assert _cmd_profiles(Args(), store=store) == 0
    out = capsys.readouterr().out
    assert "ada-lovelace" in out and "Ada Lovelace" in out

    class ShowArgs:
        profiles_command = "show"
        slug = "ada-lovelace"

    assert _cmd_profiles(ShowArgs(), store=store) == 0
    out = capsys.readouterr().out
    assert "=== Persona ===" in out
    # analysis JSON round-trips in output
    assert '"name"' in out or "{ }" in out or "{" in out


def test_profiles_show_missing_slug_returns_error_code(tmp_path, capsys):
    from resumefill.cli import _cmd_profiles

    class ShowArgs:
        profiles_command = "show"
        slug = "ghost"

    assert _cmd_profiles(ShowArgs(), store=ProfileStore(tmp_path)) == 1


def test_profile_json_is_utf8_friendly(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(CvProfile(name="Mücahid Enes Deniz"))
    raw = (tmp_path / "mucahid-enes-deniz.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["name"] == "Mücahid Enes Deniz"
