"""Browser-level tests for injected JS snippets against fixture pages.

These verify the exact code the agent ships to real job-board pages.
Requires ``playwright install chromium``; skipped otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resumefill.agent.scripts import VERIFY_FIELDS_JS, YESNO_JS

FIXTURES = Path(__file__).parent / "fixtures"
FORM_URL = (FIXTURES / "application_form.html").as_uri()


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return bool(p.chromium.executable_path) and Path(p.chromium.executable_path).exists()
    except Exception:  # noqa: BLE001 — any failure means "not available"
        return False


pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(not _chromium_available(), reason="playwright chromium not installed"),
]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        new_page = browser.new_page()
        new_page.goto(FORM_URL)
        new_page.wait_for_selector("#radio-no")
        yield new_page
        browser.close()


def _click_no(page) -> str:
    return page.evaluate(YESNO_JS)


def test_yesno_js_selects_radio_by_text(page):
    result = _click_no(page)
    assert "S1-radio: No" in result

    checked = page.get_attribute("#radio-no", "aria-checked")
    unchecked = page.get_attribute("#radio-yes", "aria-checked")
    assert checked == "true"
    assert unchecked == "false"


def test_yesno_js_is_idempotent(page):
    _click_no(page)
    second = _click_no(page)
    # Already-selected radio must not be re-clicked.
    assert second == "No Yes/No buttons found on this page."


def test_verify_reports_unfilled_required_fields(page):
    verdict = page.evaluate(VERIFY_FIELDS_JS)
    assert verdict.startswith("VERIFICATION FAILED")
    assert "Full Name" in verdict
    assert "UNCHECKED RADIO GROUP" in verdict


def test_verify_passes_after_filling_everything(page):
    page.fill("#fullname", "Mücahid Enes Deniz")
    page.fill("#postal", "34000")
    _click_no(page)

    # Simulate an invisible error banner to ensure detection logic runs both ways.
    verdict_clean = page.evaluate(VERIFY_FIELDS_JS)
    assert verdict_clean.startswith("VERIFICATION PASSED")

    page.evaluate(
        """() => {
            const el = document.createElement('div');
            el.className = 'error-banner';
            el.textContent = 'Something went wrong';
            el.style.display = 'block';
            document.body.appendChild(el);
        }"""
    )
    verdict_error = page.evaluate(VERIFY_FIELDS_JS)
    assert "ERROR MSG" in verdict_error
