"""Smart discovery and selection of Gemini models.

Queries the Google Generative AI API to discover available models and
probes a *bounded* candidate list (the built-in priority order, capped) to
pick primary/fallback/tertiary models. Probing every discovered model
burned API quota on startup in the prototype; the cap fixes that.

Note: this module uses the legacy ``google.generativeai`` SDK (pinned)
because its model-listing API is not exposed by the newer ``google.genai``
client. The deprecation warning is silenced deliberately.
"""

from __future__ import annotations

import time
import warnings

# The deprecation message starts with a newline; (?s) lets .* cross it.
warnings.filterwarnings(
    "ignore", message="(?s).*google.generativeai.*", category=FutureWarning
)

import google.generativeai as genai  # noqa: E402

# Models excluded from chat-capable selection.
_EXCLUDE_KEYWORDS = (
    "image",
    "tts",
    "robotics",
    "nano-banana",
    "embedding",
    "aqa",
    "vision",
    "deep-research",
    "computer-use",
)

# Auto-selection priority: best → worst. "latest" aliases always point to
# the newest version of each tier.
_PRIORITY_MODELS = (
    "gemini-pro-latest",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite-001",
)

# Upper bound on probe requests per auto-selection run (quota protection).
MAX_PROBE_CANDIDATES = 8


def sort_model_ids(model_ids: list[str]) -> list[str]:
    """Order model IDs by built-in priority, then alphabetically."""
    def sort_key(model_id: str):
        if model_id in _PRIORITY_MODELS:
            return (0, _PRIORITY_MODELS.index(model_id))
        return (1, model_id)

    return sorted(model_ids, key=sort_key)


def classify_probe_error(error_str: str) -> str:
    """Human-readable reason for a failed probe."""
    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
        return "Rate limited (quota exhausted)"
    if "404" in error_str or "NOT_FOUND" in error_str:
        return "Model not found"
    if "403" in error_str or "PERMISSION_DENIED" in error_str:
        return "Permission denied"
    return error_str[:100]


def discover_models(api_key: str) -> list[dict]:
    """Discover chat-capable Gemini models, sorted by selection priority."""
    genai.configure(api_key=api_key)
    models: list[dict] = []
    try:
        for m in genai.list_models():
            if "generateContent" not in m.supported_generation_methods:
                continue
            model_id = m.name.replace("models/", "")
            lower = model_id.lower()
            if any(kw in lower for kw in _EXCLUDE_KEYWORDS):
                continue
            models.append(
                {
                    "id": model_id,
                    "name": m.display_name,
                    "input_tokens": getattr(m, "input_token_limit", 0),
                    "output_tokens": getattr(m, "output_token_limit", 0),
                }
            )
    except Exception as exc:  # noqa: BLE001 — surfaced to the UI as a message
        print(f"[warn] Failed to list models: {exc}")
        return []

    ordered = sort_model_ids([m["id"] for m in models])
    rank = {mid: i for i, mid in enumerate(ordered)}
    models.sort(key=lambda m: rank[m["id"]])
    return models


def probe_model(model_id: str, api_key: str, timeout: float = 10.0) -> dict:
    """Send a minimal request to check that a model is actually usable."""
    genai.configure(api_key=api_key)

    start = time.time()
    try:
        model = genai.GenerativeModel(model_id)
        model.generate_content(
            "Reply with only the word 'OK'.",
            generation_config=genai.GenerationConfig(max_output_tokens=10, temperature=0.0),
            request_options={"timeout": timeout},
        )
        return {"available": True, "error": None, "response_time": round(time.time() - start, 2)}
    except Exception as exc:  # noqa: BLE001 — classified below
        return {
            "available": False,
            "error": classify_probe_error(str(exc)),
            "response_time": round(time.time() - start, 2),
        }


def auto_select_model(api_key: str) -> tuple[str | None, str | None, str | None, list[dict]]:
    """Pick up to three working models: (primary, fallback, tertiary).

    Only the first ``MAX_PROBE_CANDIDATES`` candidates are probed — enough
    to find three working models under normal quota conditions without
    sweeping the entire catalogue.
    """
    all_models = discover_models(api_key)
    if not all_models:
        return None, None, None, []

    name_lookup = {m["id"]: m["name"] for m in all_models}
    probe_results: list[dict] = []
    working: list[str] = []

    for model_id in [m["id"] for m in all_models][:MAX_PROBE_CANDIDATES]:
        result = probe_model(model_id, api_key)
        probe_results.append({"id": model_id, "name": name_lookup.get(model_id, model_id), **result})
        if result["available"]:
            working.append(model_id)
            if len(working) >= 3:
                break

    primary = working[0] if len(working) >= 1 else None
    fallback = working[1] if len(working) >= 2 else None
    tertiary = working[2] if len(working) >= 3 else None
    return primary, fallback, tertiary, probe_results


def get_model_display_label(model: dict) -> str:
    """Format a model dict for display in the UI dropdown."""
    tokens_k = model["input_tokens"] // 1024 if model["input_tokens"] else 0
    return f"{model['name']} ({model['id']}) — {tokens_k}K context"
