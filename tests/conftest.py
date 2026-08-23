"""Shared fixtures."""

import pytest

from resumefill.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        gemini_api_key="test-key",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path / "data",
    )
