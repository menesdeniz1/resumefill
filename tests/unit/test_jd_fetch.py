"""JD auto-fetch behaviour — canned payloads, zero network (PLAN_P5-4)."""

import pytest

from resumefill.jd_fetch import JdFetch, fetch_jd

pytestmark = pytest.mark.unit


class TestJsHeavyBoards:
    def test_workday_refuses_with_hint(self):
        result = fetch_jd("https://ing.wd3.myworkdayjobs.com/job/analyst")
        assert not result.ok
        assert "paste the description manually" in result.reason

    def test_linkedin_refuses_with_hint(self):
        result = fetch_jd("https://www.linkedin.com/jobs/view/123")
        assert not result.ok
        assert "JavaScript-only board" in result.reason


class TestGreenhouse:
    GREENHOUSE_API = (
        '{"title": "Data Analyst", "content": '
        '"<h2>About the role</h2><p>Ship analytical dashboards '
        'for the orchestrator team.</p>"}'
    )

    def test_prefers_public_api(self):
        seen = {}

        def getter(url):
            seen["url"] = url
            return self.GREENHOUSE_API.encode("utf-8")

        result = fetch_jd(
            "https://job-boards.greenhouse.io/acme/jobs/7574002003", http_get=getter
        )
        assert result.ok
        assert result.title == "Data Analyst"
        assert "dashboards" in result.text
        assert "boards-api.greenhouse.io" in seen["url"]

    def test_html_fallback_when_content_missing(self):
        page = "<title>Data Analyst</title><div id='content'><p>You will own the funnel.</p></div>"
        result = fetch_jd(
            "https://job-boards.greenhouse.io/acme/jobs/7574002003",
            http_get=lambda url: page.encode("utf-8"),
        )
        assert result.ok
        assert result.title == "Data Analyst"
        assert "own the funnel" in result.text

    def test_escaped_entities_are_unescaped_before_parsing(self):
        """Live Greenhouse finding: boards-api content ships as escaped markup."""
        payload = (
            '{"title": "Data Analyst", "content": '
            '"&lt;p&gt;&lt;strong&gt;About us&lt;/strong&gt;&lt;/p&gt;'
            '&lt;p&gt;We ship handcrafted games.&lt;/p&gt;"}'
        )
        result = fetch_jd(
            "https://job-boards.greenhouse.io/acme/jobs/42",
            http_get=lambda url: payload.encode("utf-8"),
        )
        assert result.ok
        assert "&lt;" not in result.text
        assert "handcrafted games" in result.text


class TestLever:
    def test_uses_public_api_plain_text(self):
        payload = (
            '{"title": "Backend Engineer", "text": '
            '"You will run our services across three regions."}'
        )

        result = fetch_jd(
            "https://jobs.lever.co/acme/9a8b7c6d", http_get=lambda url: payload.encode("utf-8")
        )
        assert result.ok
        assert result.title == "Backend Engineer"
        assert "three regions" in result.text

    def test_falls_back_to_page_html(self):
        payload = "{\"title\": \"Backend Engineer\", \"text\": \"\"}"
        page = "<div class='section-page'><p>Great team culture awaits.</p></div>"
        responses = {"api": payload.encode("utf-8"), "page": page.encode("utf-8")}

        def getter(url):
            return responses["api"] if "api.lever.co" in url else responses["page"]

        result = fetch_jd("https://jobs.lever.co/acme/9a8b7c6d", http_get=getter)
        assert result.ok
        assert "culture" in result.text


class TestGenericAndFailures:
    def test_generic_html_extracts_description_container(self):
        page = (
            "<title>Ops Analyst</title>"
            "<div class='job-description'><p>Keep the warehouse clean, "
            "automate the boring parts.</p></div>"
        )
        result = fetch_jd(
            "https://careers.example.com/ops-analyst", http_get=lambda url: page.encode("utf-8")
        )
        assert result.ok
        assert "warehouse" in result.text
        assert result.title == "Ops Analyst"

    def test_meta_description_fallback(self):
        page = "<title>Ops</title><meta name='description' content='Plumbing the data lakes.'>"
        result = fetch_jd(
            "https://careers.example.com/ops", http_get=lambda url: page.encode("utf-8")
        )
        assert result.ok
        assert "data lakes" in result.text

    def test_network_failure_degrades_to_hint(self):
        def getter(url):
            raise OSError("connection reset")

        result = fetch_jd("https://careers.example.com/x", http_get=getter)
        assert not result.ok
        assert "Fetch failed" in result.reason

    def test_no_content_at_all_degrades_to_hint(self):
        result = fetch_jd(
            "https://careers.example.com/x", http_get=lambda url: b"<title>only</title>"
        )
        assert not result.ok
        assert "paste the description manually" in result.reason


class TestDataclass:
    def test_ok_property(self):
        assert JdFetch(title="t", text="x").ok
        assert not JdFetch(title="t").ok
