"""Form-filling agent orchestration.

``JobFormAgent`` glues together prompt construction, guarded tools, the
browser session and the LLM, and owns the full lifecycle of one run:
local-file serving, logging, execution and teardown. UI code stays a thin
caller that supplies callbacks for streaming progress.

Heavy ``browser_use`` imports are performed lazily so importing this module
(or starting the Streamlit UI) stays fast.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from resumefill.agent.prompts import (
    build_preapproved_section,
    build_task_prompt,
    build_upload_section,
    build_verify_section,
    build_yesno_section,
)
from resumefill.config import Settings
from resumefill.logging_utils.run_logger import AgentLogger
from resumefill.platforms import get_platform_tips

# Seconds to wait after navigation before the first JS pass, letting
# job-board SPA shells render.
INITIAL_WAIT_SECONDS = 5

StepCallback = Callable[[int, Any, str], Awaitable[None]]


@dataclass
class AgentRunResult:
    """Outcome of a single agent run."""

    success: bool
    error: str | None
    summary: dict


class LocalFileServer:
    """Serves a local directory over HTTP on an ephemeral localhost port.

    Some form flows reject ``file://`` URLs; serving over loopback HTTP
    works everywhere. Ephemeral ports avoid collisions between runs.
    """

    def __init__(self, directory: Path):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port: int = self._server.server_address[1]
        self._thread: threading.Thread | None = None

    @staticmethod
    def supports(url: str) -> bool:
        return url.startswith("file:///")

    def url_for(self, url: str) -> str:
        filename = url.replace("file:///", "")
        return f"http://127.0.0.1:{self.port}/{Path(filename).name}"

    def __enter__(self) -> LocalFileServer:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._server.shutdown()
        self._server.server_close()


def _maybe_convert_file_url(url: str) -> tuple[str, LocalFileServer | None]:
    if not LocalFileServer.supports(url):
        return url, None
    server = LocalFileServer(Path(url.replace("file:///", "")).parent)
    return server.url_for(url), server


class JobFormAgent:
    """Runs one job-application filling session."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def build_logger(
        self, url: str, model_id: str | None = None, fallback_model_id: str | None = None
    ) -> AgentLogger:
        return AgentLogger(
            url=url,
            model_id=model_id or self._settings.default_model,
            fallback_model_id=fallback_model_id,
            log_dir=self._settings.log_dir,
        )

    def build_task(
        self,
        url: str,
        cv_text: str,
        analysis: dict,
        style_profile: str,
        cv_file_path: Path | None = None,
        pre_approved_answers: dict[str, str] | None = None,
        job_description: str | None = None,
    ) -> str:
        """Assemble the complete task prompt for the target URL."""
        task = build_task_prompt(
            cv_text=cv_text,
            analysis=analysis,
            style_profile=style_profile,
            platform_tips=get_platform_tips(url),
            job_description=job_description,
        )
        task += build_yesno_section()
        task += build_verify_section()
        if pre_approved_answers:
            task += build_preapproved_section(pre_approved_answers)
        if cv_file_path:
            task += build_upload_section(str(cv_file_path))
        return task

    async def run(
        self,
        url: str,
        cv_text: str,
        analysis: dict,
        style_profile: str,
        *,
        cv_file_path: Path | None = None,
        pre_approved_answers: dict[str, str] | None = None,
        job_description: str | None = None,
        model_id: str | None = None,
        fallback_model_id: str | None = None,
        logger: AgentLogger | None = None,
        on_step: StepCallback | None = None,
    ) -> AgentRunResult:
        """Execute the agent against the application URL."""
        # Imported lazily: browser-use import cost is significant and only
        # needed once a run actually starts.
        from browser_use import Agent, Browser
        from browser_use.browser.profile import BrowserProfile

        from resumefill.agent.tools import GuardedTools
        from resumefill.llm.factory import create_agent_llm

        resolved_url, file_server = _maybe_convert_file_url(url)
        parsed_host = urlparse(resolved_url).netloc or "local"

        effective_model = model_id or self._settings.default_model
        logger = logger or self.build_logger(resolved_url, effective_model, fallback_model_id)

        llm = create_agent_llm(self._settings, effective_model)
        fallback_llm = create_agent_llm(self._settings, fallback_model_id) if fallback_model_id else None

        logger.log_event("cv_analysis_done", {"name": analysis.get("name", "unknown")})

        task = self.build_task(
            resolved_url,
            cv_text,
            analysis,
            style_profile,
            cv_file_path,
            pre_approved_answers=pre_approved_answers,
            job_description=job_description,
        )

        settings = self._settings

        async def step_wrapper(state, output, step_num):
            if on_step is None:
                return
            try:
                page_url = getattr(state, "url", "") or f"https://{parsed_host}"
                logger.log_step(step_num, output, page_url)
                await on_step(step_num, output, page_url)
                if settings.step_delay_seconds > 0:
                    await asyncio.sleep(settings.step_delay_seconds)
            except Exception as exc:  # noqa: BLE001 — never kill a run over logging
                logger.log_error(str(exc), context=f"step_callback_{step_num}")

        browser = Browser(
            browser_profile=BrowserProfile(
                headless=settings.headless,
                keep_alive=settings.keep_alive,
                user_agent=settings.user_agent,
            )
        )

        tools = GuardedTools()

        initial_actions: list[dict] = [
            {"navigate": {"url": resolved_url}},
            {"wait": {"seconds": INITIAL_WAIT_SECONDS}},
        ]

        agent: Any = Agent(
            task=task,
            llm=llm,
            fallback_llm=fallback_llm,  # auto-switch on 429/503 mid-session
            browser=browser,
            tools=tools,
            register_new_step_callback=step_wrapper,
            use_vision=False,
            initial_actions=initial_actions,
            available_file_paths=[str(cv_file_path)] if cv_file_path else None,
            max_actions_per_step=settings.max_actions_per_step,
            max_failures=settings.max_failures,
            calculate_cost=True,
        )

        def _extract_usage(history) -> dict | None:
            usage = getattr(history, "usage", None)
            if usage is None:
                return None
            try:
                return {
                    "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                    "total_prompt_tokens": int(getattr(usage, "total_prompt_tokens", 0) or 0),
                    "total_completion_tokens": int(
                        getattr(usage, "total_completion_tokens", 0) or 0
                    ),
                    "total_cost": float(getattr(usage, "total_cost", 0.0) or 0.0),
                }
            except Exception:  # noqa: BLE001 — usage shape varies across versions
                return None

        try:
            with (file_server or _null_context()):
                history = await agent.run(max_steps=settings.max_steps)
            usage = _extract_usage(history)
            result = AgentRunResult(
                success=True, error=None, summary=logger.summary(success=True, usage=usage)
            )
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller/UI
            logger.log_error(str(exc), context="agent_run")
            result = AgentRunResult(
                success=False, error=str(exc), summary=logger.summary(success=False)
            )

        return result


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None
