"""LLM client construction.

Two Gemini client back-ends are intentionally used:

* ``langchain_google_genai.ChatGoogleGenerativeAI`` for standalone analysis
  calls (CV profiling, persona generation) — a plain LangChain chat model.
* ``browser_use.ChatGoogle`` for the browser agent — browser-use requires
  its own ``BaseChatModel`` interface (exposes ``.provider``, native retry
  policy, etc.).

Both are created here so model IDs, temperature and the API key come from a
single :class:`~resumefill.config.Settings` source.
"""

from __future__ import annotations

from resumefill.config import Settings


def _resolve_model(settings: Settings, model_id: str | None) -> str:
    return model_id or settings.default_model


def create_analysis_llm(settings: Settings, model_id: str | None = None):
    """LangChain-compatible Gemini model for CV analysis calls."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=_resolve_model(settings, model_id),
        google_api_key=settings.gemini_api_key,
        temperature=settings.temperature,
    )


def create_agent_llm(settings: Settings, model_id: str | None = None):
    """browser-use compatible Gemini model for the form-filling agent."""
    from browser_use import ChatGoogle

    return ChatGoogle(
        model=_resolve_model(settings, model_id),
        api_key=settings.gemini_api_key,
        temperature=settings.temperature,
    )
