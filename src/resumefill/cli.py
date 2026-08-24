"""Command-line interface.

Usage:
    resumefill                 # launch the Streamlit UI (same as `ui`)
    resumefill ui              # explicit
    resumefill run <url> [--profile SLUG | --cv PATH] [--jd FILE]
                       [--dry-run] [--headless] [--model ID]
    resumefill profiles list
    resumefill profiles show <slug>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    # Required by Playwright subprocess plumbing before any loop starts.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from resumefill.agent.service import JobFormAgent  # noqa: E402
from resumefill.answers.generator import QUESTION_SLOTS, generate_answer_pack  # noqa: E402
from resumefill.config import load_settings  # noqa: E402
from resumefill.cv.analyzer import analyze_cv, generate_style_profile  # noqa: E402
from resumefill.llm.factory import create_analysis_llm  # noqa: E402
from resumefill.profiles.store import ProfileStore  # noqa: E402
from resumefill.text_utils import sanitize_text  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resumefill",
        description="Autonomous job-application form filler.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("ui", help="Launch the Streamlit web UI")

    run = sub.add_parser("run", help="Fill one job application form")
    run.add_argument("url", help="Job application URL")
    source = run.add_mutually_exclusive_group()
    source.add_argument("--profile", help="Slug of a saved CV profile")
    source.add_argument("--cv", type=Path, help="CV file (PDF/TXT); analyzed and saved")
    run.add_argument("--jd", type=Path, help="File containing the job description")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate draft answers and print them; do not open a browser",
    )
    run.add_argument("--headless", action="store_true", help="Run browser invisibly")
    run.add_argument("--model", help="Override the primary Gemini model")

    profiles = sub.add_parser("profiles", help="Manage saved CV profiles")
    profiles_sub = profiles.add_subparsers(dest="profiles_command", required=True)
    profiles_sub.add_parser("list", help="List saved profiles")
    show = profiles_sub.add_parser("show", help="Show a profile's analysis and persona")
    show.add_argument("slug")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv == ["ui"]:
        return _launch_ui()

    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "profiles":
        return _cmd_profiles(args)
    return _launch_ui()  # unreachable guard


# ── UI launcher ──────────────────────────────────────────────────────────────

def _launch_ui() -> int:
    from streamlit.web import cli as stcli

    app_path = Path(__file__).resolve().parent / "ui" / "app.py"
    sys.argv = ["streamlit", "run", str(app_path), *sys.argv[1:]]
    stcli.main()
    return 0


# ── helpers ──────────────────────────────────────────────────────────────────

def _resolve_profile_source(args, settings, store: ProfileStore):
    """Return (analysis, style_profile, cv_text, sha256|None) or None on error."""
    if args.profile:
        try:
            profile = store.load(args.profile)
        except FileNotFoundError:
            print(f"error: profile {args.profile!r} not found "
                  f"(see `resumefill profiles list`)")
            return None
        return (
            profile.analysis,
            profile.style_profile,
            profile.cv_text,
            profile.source_cv_sha256,
        )

    cv_path: Path | None = args.cv or settings.default_cv_path()
    if cv_path is None:
        print("error: provide --cv PATH, --profile SLUG, or data/cv.txt")
        return None
    from resumefill.cv.extract import load_cv_file

    extraction = load_cv_file(cv_path)
    if extraction.is_empty:
        print(f"error: no text extracted from {cv_path}")
        return None
    for warning in extraction.warnings:
        print(f"warning: {warning}")

    import hashlib

    llm = create_analysis_llm(settings)
    analysis = analyze_cv(extraction.text, llm)
    style_profile = generate_style_profile(analysis, llm)
    profile, slug = store.save(
        store.build_from_analysis(analysis, style_profile, extraction.text,
                                  hashlib.sha256(cv_path.read_bytes()).hexdigest())
    )
    print(f"profile saved: {profile.name} ({slug})")
    return analysis, style_profile, extraction.text, profile.source_cv_sha256


def _print_answer_pack(answers: dict[str, str]) -> None:
    print("\n=== Draft answers (edit & reuse via UI later) ===")
    for slot, answer in answers.items():
        meta: Any = QUESTION_SLOTS.get(slot, {})
        print(f"\n[{meta.get('label', slot)}]")
        print(answer)


def _cmd_run(args) -> int:
    settings = load_settings()
    if not settings.has_api_key:
        print("error: GEMINI_API_KEY is not set (see .env.example)")
        return 1

    store = ProfileStore(settings.profiles_dir)
    resolved = _resolve_profile_source(args, settings, store)
    if resolved is None:
        return 1
    analysis, style_profile, cv_text, _sha = resolved

    job_description = None
    if args.jd:
        job_description = args.jd.read_text(encoding="utf-8", errors="replace")

    if args.headless:
        from dataclasses import replace as dc_replace

        settings = dc_replace(settings, headless=True)
    model_id = args.model or settings.default_model

    agent_service = JobFormAgent(settings)

    pre_approved = None
    if args.dry_run:
        jd_text = sanitize_text(job_description or "")
        if jd_text or args.url:
            from resumefill.analytics import aggregate_runs
            from resumefill.screening import screen_jd

            history_urls = {
                record.url for record in aggregate_runs(settings.log_dir)["recent"]
            }
            flags = screen_jd(jd_text, args.url, history_urls)
            if flags:
                print("\n=== Posting screening ===")
                emoji = {"danger": "RED", "warn": "YELLOW", "info": "INFO"}
                for flag in flags:
                    print(f"[{emoji[flag.level]:<6}] {flag.code}: {flag.message}")

        llm = create_analysis_llm(settings, model_id)

        if job_description and job_description.strip():
            from resumefill.scoring import evaluate_fit

            print("scoring fit…")
            report = evaluate_fit(
                cv_text=cv_text,
                jd_text=job_description,
                llm=llm,
            )
            print(f"\n=== Fit Score: {report.global_score:.1f}/5 ({report.verdict}) ===")
            for dim in report.dimensions:
                print(f"  {dim.name:<18} {dim.score:>4.1f}  {dim.rationale}")
            if report.red_flags:
                print("  red flags: " + " · ".join(report.red_flags))
            print(f"  → {report.summary}")

        pack = generate_answer_pack(
            analysis=analysis,
            style_profile=style_profile,
            cv_text=cv_text,
            llm=llm,
            job_description=job_description,
        )
        if not pack.answers:
            print("error: the model returned no usable answers", file=sys.stderr)
            return 1
        _print_answer_pack(pack.answers)
        return 0

    async def on_step(step_num: int, output, page_url: str) -> None:
        goal = getattr(output, "next_goal", None) or getattr(output, "thinking", "…")
        print(f"\n--- step {step_num} --- {goal}")
        actions = getattr(output, "action", None)
        if actions:
            print("    page:", page_url)

    def execute():
        return asyncio.run(
            agent_service.run(
                args.url,
                cv_text,
                analysis,
                style_profile,
                pre_approved_answers=pre_approved,
                job_description=job_description,
                model_id=model_id,
                on_step=on_step,
            )
        )

    result = execute()
    summary = result.summary
    outcome = "done" if result.success else f"stopped: {result.error}"
    print(f"\n{outcome} · steps={summary['total_steps']} "
          f"errors={summary['total_errors']} · log={summary['log_file']}")
    if result.success:
        print("Review the form in the browser and submit manually.")
    return 0 if result.success else 1


def _cmd_profiles(args, store: ProfileStore | None = None) -> int:
    store = store or ProfileStore(load_settings().profiles_dir)
    if args.profiles_command == "list":
        pairs = store.list()
        if not pairs:
            print("No saved profiles.")
            return 0
        print(f"{'SLUG':<28} {'NAME':<24} TITLE")
        for slug, profile in pairs:
            print(f"{slug:<28} {profile.name:<24} {profile.title}")
        return 0

    try:
        profile = store.load(args.slug)
    except FileNotFoundError:
        print(f"error: profile {args.slug!r} not found")
        return 1
    import json

    print(json.dumps(profile.analysis, ensure_ascii=False, indent=2))
    print("\n=== Persona ===")
    print(profile.style_profile)
    return 0
