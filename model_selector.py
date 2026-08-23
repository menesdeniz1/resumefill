"""
Model Selector — Smart auto-discovery and selection of Gemini models.

Queries the Google Generative AI API to discover available models,
probes them for availability, and auto-selects the best working model.
"""

import warnings
import os

# Suppress deprecation warnings from google.generativeai
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

import google.generativeai as genai


# Models to exclude — not useful for text chat tasks
_EXCLUDE_KEYWORDS = [
    "image",
    "tts",
    "robotics",
    "nano-banana",
    "embedding",
    "aqa",
    "vision",  # old vision-only models
    "deep-research",
    "computer-use",
]

# Priority order for auto-selection: BEST → WORST
# "latest" aliases always point to the newest/best version of each tier
_PRIORITY_MODELS = [
    # Tier 1: Latest aliases (auto-update to newest, best choice)
    "gemini-pro-latest",         # always the best pro model
    "gemini-flash-latest",       # always the best flash model
    "gemini-flash-lite-latest",  # always the best lite model
    # Tier 2: Newest versioned models (explicit, stable)
    "gemini-2.5-pro",            # most powerful, but slower
    "gemini-2.5-flash",          # great balance of speed + quality
    "gemini-2.5-flash-lite",     # fast + lightweight
    # Tier 3: Older but reliable
    "gemini-2.0-flash",          # proven stable
    "gemini-2.0-flash-lite",     # lightweight fallback
    # Tier 4: Pinned versions (last resort)
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite-001",
]


def discover_models(api_key: str) -> list[dict]:
    """
    Discover all chat-capable Gemini models available with the given API key.

    Args:
        api_key: Google Gemini API key.

    Returns:
        List of dicts with keys: id, name, input_tokens, output_tokens
        Sorted by priority (preferred models first), then alphabetically.
    """
    genai.configure(api_key=api_key)

    models = []
    try:
        for m in genai.list_models():
            # Only include models that support content generation
            if "generateContent" not in m.supported_generation_methods:
                continue

            # Extract the short model ID (e.g., "gemini-2.0-flash")
            model_id = m.name.replace("models/", "")

            # Exclude non-chat models
            lower_id = model_id.lower()
            if any(kw in lower_id for kw in _EXCLUDE_KEYWORDS):
                continue

            models.append({
                "id": model_id,
                "name": m.display_name,
                "input_tokens": getattr(m, "input_token_limit", 0),
                "output_tokens": getattr(m, "output_token_limit", 0),
            })
    except Exception as e:
        print(f"⚠️ Failed to list models: {e}")
        return []

    # Sort: priority models first (in order), then rest alphabetically
    def sort_key(model):
        model_id = model["id"]
        if model_id in _PRIORITY_MODELS:
            return (0, _PRIORITY_MODELS.index(model_id))
        return (1, model_id)

    models.sort(key=sort_key)
    return models


def probe_model(model_id: str, api_key: str, timeout: float = 10.0) -> dict:
    """
    Test if a model is available by sending a minimal request.

    Args:
        model_id: The model ID (e.g., "gemini-2.0-flash").
        api_key: Google Gemini API key.
        timeout: Max seconds to wait for response.

    Returns:
        Dict with: available (bool), error (str or None), response_time (float)
    """
    import time

    genai.configure(api_key=api_key)

    start = time.time()
    try:
        model = genai.GenerativeModel(model_id)
        response = model.generate_content(
            "Reply with only the word 'OK'.",
            generation_config=genai.GenerationConfig(
                max_output_tokens=10,
                temperature=0.0,
            ),
            request_options={"timeout": timeout},
        )
        elapsed = time.time() - start
        return {"available": True, "error": None, "response_time": round(elapsed, 2)}
    except Exception as e:
        elapsed = time.time() - start
        error_str = str(e)
        # Classify the error
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            reason = "Rate limited (quota exhausted)"
        elif "404" in error_str or "NOT_FOUND" in error_str:
            reason = "Model not found"
        elif "403" in error_str or "PERMISSION_DENIED" in error_str:
            reason = "Permission denied"
        else:
            reason = error_str[:100]
        return {"available": False, "error": reason, "response_time": round(elapsed, 2)}


def auto_select_model(api_key: str) -> tuple[str | None, str | None, str | None, list[dict]]:
    """
    Automatically select the best THREE available models (primary + fallback + tertiary).

    Probes models in priority order and picks the first three that respond.
    The fallback/tertiary are used for mid-session recovery on quota exhaustion.

    Args:
        api_key: Google Gemini API key.

    Returns:
        Tuple of (primary, fallback, tertiary, probe_results)
        Any ID can be None if not enough models are available.
    """
    # First discover all models
    all_models = discover_models(api_key)
    if not all_models:
        return None, None, None, []

    # Build a lookup for display names
    name_lookup = {m["id"]: m["name"] for m in all_models}
    available_ids = {m["id"] for m in all_models}

    probe_results = []
    working_models = []  # collect up to 3

    # Probe models in order (priority ones first, then alphabetical)
    ordered_ids = [m["id"] for m in all_models]
    for model_id in ordered_ids:

        result = probe_model(model_id, api_key)
        probe_results.append({
            "id": model_id,
            "name": name_lookup.get(model_id, model_id),
            **result,
        })

        if result["available"]:
            working_models.append(model_id)
            if len(working_models) >= 3:
                break  # Got primary + fallback + tertiary

    primary = working_models[0] if len(working_models) >= 1 else None
    fallback = working_models[1] if len(working_models) >= 2 else None
    tertiary = working_models[2] if len(working_models) >= 3 else None
    return primary, fallback, tertiary, probe_results


def get_model_display_label(model: dict) -> str:
    """Format a model dict for display in a UI dropdown."""
    tokens_k = model["input_tokens"] // 1024 if model["input_tokens"] else 0
    return f"{model['name']} ({model['id']}) — {tokens_k}K context"
