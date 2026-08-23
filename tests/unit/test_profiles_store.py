import json
from pathlib import Path

import pytest

from resumefill.profiles.store import SCHEMA_VERSION, CvProfile, ProfileStore, make_slug


@pytest.fixture
def store(tmp_path):
    return ProfileStore(tmp_path / "profiles")


def _sample_profile(name="Mücahid Enes Deniz", **overrides):
    data = {
        "name": name,
        "email": "test@example.com",
        "title": "Software Engineer",
        "analysis": {"key_achievements": ["Reduced costs by 88%"]},
        "style_profile": "You are concise and metric-driven...",
        "cv_text": "FULL CV TEXT",
        "source_cv_sha256": "abc123",
    }
    data.update(overrides)
    return CvProfile(**data)


def test_make_slug_strips_accents_and_symbols():
    assert make_slug("Mücahid Enes Deniz") == "mucahid-enes-deniz"
    assert make_slug("  Ada   Lovelace! ") == "ada-lovelace"
    assert make_slug("") == "profile"
    assert make_slug("İÖÇŞÜğ") == "iocsug"


def test_save_assigns_slug_and_schema(store):
    stored, slug = store.save(_sample_profile())
    assert slug == "mucahid-enes-deniz"
    path = store._path(slug)  # noqa: SLF001 — white-box assertion of layout
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION
    assert stored.created_at <= stored.updated_at


def test_save_dedupes_colliding_slugs(store):
    _, first = store.save(_sample_profile(name="Ada Lovelace"))
    _, second = store.save(_sample_profile(name="Ada Lovelace"))
    _, third = store.save(_sample_profile(name="Ada Lovelace"))
    assert (first, second, third) == ("ada-lovelace", "ada-lovelace-2", "ada-lovelace-3")


def test_save_with_explicit_slug_overwrites_and_preserves_created_at(store):
    original, _ = store.save(_sample_profile())
    edited = _sample_profile(email="new@example.com")
    store.save(edited, slug="mucahid-enes-deniz")

    reloaded = store.load("mucahid-enes-deniz")
    assert reloaded.email == "new@example.com"
    assert reloaded.created_at == original.created_at


def test_load_roundtrip_keeps_all_fields(store):
    profile = _sample_profile()
    stored, slug = store.save(profile)
    loaded = store.load(slug)
    assert loaded == stored


def test_load_missing_raises(store):
    with pytest.raises(FileNotFoundError):
        store.load("ghost")


def test_list_sorted_by_name_and_skips_corrupt(store):
    store.save(_sample_profile(name="Zoe"))
    store.save(_sample_profile(name="Alice"))
    corrupt = store._dir / "broken.json"  # noqa: SLF001 — fixture writes junk file
    corrupt.write_text("{not json", encoding="utf-8")

    pairs = store.list()
    assert [p.name for _, p in pairs] == ["Alice", "Zoe"]
    assert all(isinstance(slug, str) and slug for slug, _ in pairs)


def test_from_dict_ignores_unknown_keys_for_forward_compat():
    data = _sample_profile().to_dict() | {"future_field": {"x": 1}}
    profile = CvProfile.from_dict(data)
    assert not hasattr(profile, "future_field")


def test_update_edits_key_fields_only_and_bumps_updated_at(store):
    stored, slug = store.save(_sample_profile())
    updated = store.update(
        slug,
        name="M. E. Deniz",
        phone="+90 555",
        title="Senior Software Engineer",
        email="me@example.com",
    )
    assert updated.name == "M. E. Deniz"
    assert updated.phone == "+90 555"
    # Non-editable fields untouched:
    assert updated.cv_text == "FULL CV TEXT"
    assert updated.analysis == stored.analysis
    assert updated.updated_at >= stored.updated_at


def test_delete_returns_true_then_false(store):
    _, slug = store.save(_sample_profile())
    assert store.delete(slug) is True
    assert store.delete(slug) is False
    assert store.list() == []


def test_invalid_slug_rejected(store):
    with pytest.raises(ValueError):
        store.load("../escape")


def test_build_from_analysis_normalizes_fields():
    analysis = {
        "name": "Test Person",
        "email": "t@e.com",
        "phone": "555",
        "title": "Data Analyst",
        "skills": {"technical": ["Python"], "tools": [], "soft": ["Leadership"]},
        "extra_top_level": "kept",
    }
    profile = ProfileStore(Path("unused")).build_from_analysis(
        analysis, style_profile="persona", cv_text="CV", source_cv_sha256=None
    )
    assert profile.name == "Test Person"
    assert profile.analysis["skills"] == {"technical": ["Python"], "tools": [], "soft": ["Leadership"]}
    assert profile.analysis["extra_top_level"] == "kept"
    assert profile.source_cv_sha256 is None
