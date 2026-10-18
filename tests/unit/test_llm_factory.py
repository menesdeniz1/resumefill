"""LLM factory behaviour — both back-ends from one Settings source."""

import pytest

from resumefill.llm.factory import create_agent_llm, create_analysis_llm

pytestmark = pytest.mark.unit


class TestAgentLlmRetryPolicy:
    """Real-run finding: 429 quota windows (>40s) outlast default ~1s
    retries, so the client must be patient instead of failing fast."""

    def test_agent_llm_retries_are_patient(self, settings):
        llm = create_agent_llm(settings, "gemini-flash-lite-latest")
        assert llm.max_retries == 8
        assert llm.retry_base_delay == 10.0
        assert llm.retry_max_delay == 120.0
        assert llm.model == "gemini-flash-lite-latest"

    def test_agent_llm_defaults_to_default_model(self, settings):
        llm = create_agent_llm(settings)
        assert llm.model == settings.default_model

    def test_agent_llm_retries_the_transient_codes(self, settings):
        llm = create_agent_llm(settings)
        assert set(llm.retryable_status_codes) >= {429, 500, 502, 503, 504}


class TestAnalysisLlm:
    def test_analysis_llm_uses_requested_model(self, settings):
        llm = create_analysis_llm(settings, "gemini-2.5-flash")
        assert llm.model == "gemini-2.5-flash"
        assert llm.google_api_key.get_secret_value() == "test-key"
