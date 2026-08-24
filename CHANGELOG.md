# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Posting screening** (`P4-2`): zero-token rule-based legitimacy flags
  (fee requests, crypto payment, personal apply e-mails, commission-only
  language, shortened URLs, repost detection via URL normalization) shown
  in the dry-run flow before any LLM call.
- **Fit score rubric** (`P4-1`): one-call CV-vs-JD assessment — five scored
  dimensions with evidence-based rationale, holistic 1-5 global score,
  verdict (`strong/reasonable/stretch/skip`), red flags and summary;
  structured output first with tolerant fallback.
- **STAR story bank** (`P4-4`): `data/stories.yml` (see example file);
  relevant stories selected by token overlap and embedded into draft
  answers as grounding. Optional — absent file changes nothing.
- **Application funnel** (`P4-3`): record post-application outcomes
  (`resumefill outcome <url> --status …`, or the UI form); latest-wins
  JSONL store with status counts, per-platform advance rates in Run History.
- Profile store: analyzed CV profiles persist as `data/profiles/<slug>.json`
  (schema-versioned, atomic writes, collision-safe slugs); UI supports
  select/edit/delete; runs from a saved profile need zero analysis calls.
- Dry-run mode: one-call draft answers for common question slots
  (about-you, strengths, weakness, notice period, salary, conflict,
  why-leaving, why-this-role); editable in the UI before the run.
- Pre-approved answer embedding: reviewed drafts are injected into the task
  prompt and used verbatim on matching form questions.
- Job-description tailoring: paste a JD to steer both drafted and live
  answers (`JOB DESCRIPTION` prompt section).
- Run-history analytics panel over `logs/*.jsonl` (success rate,
  per-platform breakdown, average steps, recent runs table); run summaries
  now record explicit success/failure.
- Thin CLI: `resumefill run <url> [--profile|--cv] [--jd] [--dry-run]
  [--headless]`, `resumefill profiles list|show`,
  `resumefill outcome <url> --status …`; bare `resumefill` still
  launches the web UI.

### Changed
- CV profile extraction now prefers native structured output
  (`with_structured_output`), degrading gracefully to prompt+regex parsing;
  pydantic added as a direct dependency.
- Prototype root-level scripts restructured into the `src/resumefill`
  package with a layered architecture and fully pinned dependencies.

### Fixed
- PDF mojibake corruption of names/answers (unicode sanitization pipeline).
- YES/No handler re-clicking already-selected radios on repeat pages.
- Startup quota burn: model probing is capped instead of sweeping every
  discovered Gemini model.
- Per-step artificial 10 s delay removed (configurable via env now).
- Agent hard-capped by `max_steps` to bound cost; submit blocking enforced
  in code (`GuardedTools`) rather than only prompted.
