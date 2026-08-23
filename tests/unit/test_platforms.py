import pytest

from resumefill.platforms import Platform, detect_platform, get_platform_tips


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://ing.wd3.myworkdayjobs.com/en-US/job/123", Platform.WORKDAY),
        ("https://acme.wd5.myworkdaysite.com/recruit", Platform.WORKDAY),
        ("https://jobs.lever.co/acme/abc123", Platform.LEVER),
        ("https://jobs.eu.lever.co/acme/abc", Platform.LEVER),
        ("https://boards.greenhouse.io/acme/jobs/123", Platform.GREENHOUSE),
        ("https://www.linkedin.com/jobs/view/123456", Platform.LINKEDIN),
        ("https://careers.example.com/apply/1", Platform.GENERIC),
        ("not a url at all", Platform.GENERIC),
        ("", Platform.GENERIC),
    ],
)
def test_detect_platform(url, expected):
    assert detect_platform(url) == expected


def test_tips_are_scoped_to_detected_platform():
    tips = get_platform_tips("https://ing.wd3.myworkdayjobs.com/job/x")
    assert "WORKDAY-SPECIFIC" in tips
    assert "LEVER-SPECIFIC" not in tips
    assert "GENERIC SITE GUIDANCE" in tips  # universal section always included


def test_generic_url_gets_only_generic_tips():
    tips = get_platform_tips("https://careers.example.com/apply")
    assert "GENERIC SITE GUIDANCE" in tips
    assert "LINKEDIN EASY APPLY-SPECIFIC" not in tips
