"""Memory store behaviour — persistent question/answer bank (PLAN_P5)."""

import pytest

from resumefill.memory import (
    MEMORY_RIDE_LIMIT,
    MemoryStore,
    approved_answer_map,
    normalize_question,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "data")


class TestNormalizeQuestion:
    def test_drops_punctuation_and_collapses_whitespace(self):
        assert normalize_question("Where did you hear  about us?") == normalize_question(
            "where did you hear about us"
        )

    def test_case_insensitive(self):
        assert normalize_question("APPLYING For") == normalize_question("Applying for")


class TestPersistence:
    def test_add_creates_file_and_roundtrips(self, store):
        added, created = store.add_or_update(
            "Notice period?", "I can start immediately after a 1-month notice.",
            approved=True,
        )
        assert created is False
        assert added.approved is True
        assert added.source == "manual"

        reloaded = MemoryStore(store.path.parent)
        entries = reloaded.entries()
        assert len(entries) == 1
        assert entries[0].question == "Notice period?"
        assert entries[0].answer.startswith("I can start")

    def test_missing_file_means_no_entries(self, store):
        assert store.entries() == []
        assert store.find("anything") is None

    def test_malformed_yaml_is_tolerated(self, store):
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("answers: [ {question: broken", encoding="utf-8")
        assert store.entries() == []

    def test_invalid_rows_skipped_valid_kept(self, store):
        import yaml

        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            yaml.safe_dump(
                {
                    "answers": [
                        {"question": "", "answer": "no question"},
                        {"question": "Good question", "answer": "good answer", "approved": True},
                    ]
                }
            ),
            encoding="utf-8",
        )
        entries = store.entries()
        assert len(entries) == 1
        assert entries[0].approved is True


class TestMatching:
    def test_exact_normalized_match(self, store):
        store.add_or_update("Why this company?", "Your games look handcrafted.")
        found = store.find("why this company?")
        assert found is not None
        assert found.answer == "Your games look handcrafted."

    def test_fuzzy_match_above_threshold(self, store):
        store.add_or_update(
            "Are you legally authorized to work in this country?", "Yes."
        )
        found = store.find("Are you legally authorized to work in the country?")
        assert found is not None
        assert found.answer == "Yes."

    def test_unrelated_question_returns_none(self, store):
        store.add_or_update("Notice period?", "1 month.")
        assert store.find("What is your favourite colour in hexadecimal?") is None


class TestMutations:
    def test_add_or_update_replaces_answer_in_place(self, store):
        store.add_or_update("Notice period?", "1 month.")
        updated, was_update = store.add_or_update("Notice Period!", "2 months.")
        assert was_update is True
        assert len(store.entries()) == 1
        assert store.entries()[0].answer == "2 months."
        assert store.entries()[0].approved is False

    def test_update_preserves_usage_stats(self, store):
        store.add_or_update("Notice period?", "1 month.", approved=True)
        store.mark_used("Notice period?")
        store.add_or_update("Notice period?", "2 months.", approved=True)
        entry = store.entries()[0]
        assert entry.times_used == 1
        assert entry.last_used is not None

    def test_approve_sets_flag(self, store):
        store.add_or_update("Notice period?", "1 month", approved=False)
        assert store.approve("Notice period?") is True
        assert store.entries(only_approved=True)[0].question == "Notice period?"

    def test_approve_missing_returns_false(self, store):
        assert store.approve("Nothing here") is False

    def test_delete(self, store):
        store.add_or_update("Notice period?", "1 month")
        assert store.delete("N t i c e period") is False  # ratio below threshold
        assert store.delete("Notice period?") is True
        assert store.entries() == []
        assert store.delete("Notice period?") is False

    def test_mark_used_bumps_counter_and_date(self, store):
        store.add_or_update("Notice period?", "1 month")
        assert store.mark_used("Notice period?") is True
        entry = store.entries()[0]
        assert entry.times_used == 1
        assert entry.last_used is not None


class TestApprovedAnswerMap:
    def _filled_store(self, tmp_path):
        store = MemoryStore(tmp_path / "data")
        for question in ["Q one", "Q two", "Q three"]:
            store.add_or_update(question, f"answer {question}", approved=True)
        return store

    def test_only_approved_entries_ride(self, tmp_path):
        store = self._filled_store(tmp_path)
        store.add_or_update("Unapproved q", "draft", approved=False)
        ride = approved_answer_map(store)
        assert set(ride) == {"Q one", "Q two", "Q three"}

    def test_most_used_first(self, tmp_path):
        store = self._filled_store(tmp_path)
        store.mark_used("Q two")
        store.mark_used("Q two")
        ride = approved_answer_map(store, limit=2)
        assert list(ride) == ["Q two", "Q one"]

    def test_cap_applied(self, tmp_path):
        store = self._filled_store(tmp_path)
        for i in range(MEMORY_RIDE_LIMIT + 5):
            store.add_or_update(f"Extra {i}", f"answer {i}", approved=True)
        assert len(approved_answer_map(store)) == MEMORY_RIDE_LIMIT

    def test_empty_store_maps_to_empty(self, tmp_path):
        assert approved_answer_map(MemoryStore(tmp_path / "data")) == {}
