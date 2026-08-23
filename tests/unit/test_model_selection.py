from types import SimpleNamespace

import resumefill.model_selection as ms


def test_sort_model_ids_priority_order():
    ordered = ms.sort_model_ids(
        ["gemini-2.0-flash", "gemini-pro-latest", "aardvark-model", "gemini-flash-latest"]
    )
    assert ordered[:3] == ["gemini-pro-latest", "gemini-flash-latest", "gemini-2.0-flash"]
    assert ordered[3] == "aardvark-model"  # unknowns come last, alphabetically


def test_classify_probe_error_mapping():
    assert "Rate limited" in ms.classify_probe_error("429 RESOURCE_EXHAUSTED")
    assert "not found" in ms.classify_probe_error("404 NOT_FOUND")
    assert "Permission denied" in ms.classify_probe_error("403 PERMISSION_DENIED")
    assert "weird failure" in ms.classify_probe_error("weird failure")


def _fake_model(mid, display=None, inp=1000):
    return SimpleNamespace(
        name=f"models/{mid}",
        supported_generation_methods=["generateContent"],
        display_name=display or mid,
        input_token_limit=inp,
        output_token_limit=500,
    )


def test_discover_models_filters_and_sorts(monkeypatch):
    fake_models = [
        _fake_model("gemini-embedding-001"),
        _fake_model("gemini-image-gen"),
        _fake_model("zzz-custom"),
        _fake_model("gemini-flash-latest", "Gemini Flash Latest"),
    ]
    monkeypatch.setattr(ms.genai, "configure", lambda api_key: None)
    monkeypatch.setattr(ms.genai, "list_models", lambda: fake_models)

    models = ms.discover_models("key")
    ids = [m["id"] for m in models]
    assert "gemini-embedding-001" not in ids
    assert "gemini-image-gen" not in ids
    assert ids == ["gemini-flash-latest", "zzz-custom"]


def test_auto_select_stops_after_three_working_models(monkeypatch):
    fake_models = [_fake_model(f"model-{i:02d}") for i in range(12)]
    monkeypatch.setattr(ms.genai, "configure", lambda api_key: None)
    monkeypatch.setattr(ms.genai, "list_models", lambda: fake_models)

    probe_calls = []

    def fake_probe(model_id, api_key, timeout=10.0):
        probe_calls.append(model_id)
        return {"available": True, "error": None, "response_time": 0.1}

    monkeypatch.setattr(ms, "probe_model", fake_probe)

    primary, fallback, tertiary, results = ms.auto_select_model("key")
    assert len(probe_calls) == 3  # early exit once three models work
    assert (primary, fallback, tertiary) == ("model-00", "model-01", "model-02")


def test_auto_select_caps_probe_requests_when_all_fail(monkeypatch):
    # 12 discoverable models, none working → probing must stop at the cap.
    fake_models = [_fake_model(f"model-{i:02d}") for i in range(12)]
    monkeypatch.setattr(ms.genai, "configure", lambda api_key: None)
    monkeypatch.setattr(ms.genai, "list_models", lambda: fake_models)

    probe_calls = []

    def fake_probe(model_id, api_key, timeout=10.0):
        probe_calls.append(model_id)
        return {"available": False, "error": "Rate limited", "response_time": 0.1}

    monkeypatch.setattr(ms, "probe_model", fake_probe)

    primary, fallback, tertiary, results = ms.auto_select_model("key")
    assert len(probe_calls) == ms.MAX_PROBE_CANDIDATES
    assert (primary, fallback, tertiary) == (None, None, None)
    assert all(not r["available"] for r in results)


def test_auto_select_survives_partial_failures(monkeypatch):
    """Failures consume probe budget; successes after them are still picked."""
    fake_models = [_fake_model(f"model-{i:02d}") for i in range(12)]
    monkeypatch.setattr(ms.genai, "configure", lambda api_key: None)
    monkeypatch.setattr(ms.genai, "list_models", lambda: fake_models)

    probe_calls = []

    def fake_probe(model_id, api_key, timeout=10.0):
        probe_calls.append(model_id)
        index = int(model_id.split("-")[1])
        available = index >= 2
        return {
            "available": available,
            "error": None if available else "Model not found",
            "response_time": 0.1,
        }

    monkeypatch.setattr(ms, "probe_model", fake_probe)

    primary, fallback, tertiary, _ = ms.auto_select_model("key")
    assert (primary, fallback, tertiary) == ("model-02", "model-03", "model-04")
    assert len(probe_calls) == 5  # two failures + three successes


def test_get_model_display_label():
    label = ms.get_model_display_label({"name": "Gemini Flash", "id": "g-f", "input_tokens": 1_048_576})
    assert "Gemini Flash" in label and "1024K context" in label
