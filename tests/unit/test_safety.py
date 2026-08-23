import pytest

from resumefill.agent.safety import is_submit_element, node_is_submit


class FakeNode:
    def __init__(self, tag_name, attributes=None, text=""):
        self.tag_name = tag_name
        self.attributes = attributes or {}
        self._text = text

    def get_all_children_text(self):
        return self._text


@pytest.mark.parametrize(
    ("tag", "attrs", "text", "expected"),
    [
        # exact visible text matches — any tag (Workday renders div buttons)
        ("button", {}, "Submit", True),
        ("span", {}, "Submit Application", True),
        ("div", {"role": "button"}, "Gönder", True),
        ("a", {}, "Send Application", True),
        # case/whitespace normalization
        ("button", {}, "  submit ", True),
        # input semantics
        ("input", {"type": "submit"}, "", True),
        ("input", {"type": "submit"}, "Next", True),  # type wins over text
        ("input", {"type": "button", "value": "Submit"}, "", True),
        # attribute hints on button-like elements
        ("div", {"data-automation-id": "submitApplication"}, "Apply", True),
        ("button", {"id": "submit_button"}, "Go", True),
        ("span", {"aria-label": "Submit application"}, "", True),
        # negatives — navigation must keep working
        ("button", {}, "Next", False),
        ("button", {}, "Continue", False),
        ("button", {}, "Save and Continue", False),
        ("div", {}, "Apply", False),
        # form fields never count, even with submit-like content
        ("textarea", {}, "submit", False),
        ("textarea", {}, "I will submit my thesis", False),
        ("select", {}, "submit", False),
        ("input", {"type": "text", "value": "submit"}, "", False),
    ],
)
def test_is_submit_element(tag, attrs, text, expected):
    assert is_submit_element(tag, attrs, text) == expected


def test_node_wrapper_uses_text_and_attributes():
    assert node_is_submit(FakeNode("button", {}, "Submit Application"))
    assert not node_is_submit(FakeNode("button", {}, "Next"))


def test_node_wrapper_survives_missing_helpers():
    class Bare:
        tag_name = "button"
        attributes = {}

    assert node_is_submit(Bare()) is False
