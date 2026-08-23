"""Code-level submit guard.

The prompt tells the model never to click Submit — but prompts are
advisory. This module enforces the rule in code by wrapping browser-use's
``click`` and ``send_keys`` actions: before any click is dispatched, the
target element is inspected; before Enter is sent, the focused element is
checked — single-line fields are blocked while textareas remain allowed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Normalized (lowercase, stripped) visible texts that indicate a final
# submission action. Checked against ANY clickable element because job-board
# UIs (e.g. Workday) often render buttons as styled <div>/<span> elements.
# Conservative on purpose: navigation texts such as "Apply", "Next" or
# "Continue" must keep working.
_SUBMIT_TEXTS = frozenset(
    {
        "submit",
        "submit application",
        "submit now",
        "send application",
        "gönder",
        "başvur",
        "başvuruyu gönder",
        "başvuruyu tamamla",
    }
)

# Substrings checked against id / name / aria-label / data-automation-id of
# button-like elements only.
_SUBMIT_ATTR_HINTS = (
    "submitapplication",
    "submit_button",
    "submitbutton",
    "sendsubmission",
)

# Form fields whose *content* must never trigger the guard.
_FIELD_TAGS = frozenset({"textarea", "select"})

# <input> types whose value attribute represents a button caption rather
# than user-entered content.
_BUTTON_INPUT_TYPES = frozenset({"button", "image", "reset"})

# <input> types that are single-line text fields where Enter can submit.
_SINGLE_LINE_INPUT_TYPES = frozenset(
    {"", "text", "email", "password", "search", "tel", "url", "number"}
)


def _attr_haystack(attributes: Mapping[str, str]) -> tuple[str, str]:
    """Raw and whitespace-collapsed id/name/aria/data-automation attributes."""
    raw = "|".join(
        filter(
            None,
            (
                attributes.get("id", ""),
                attributes.get("name", ""),
                attributes.get("aria-label", ""),
                attributes.get("data-automation-id", ""),
            ),
        )
    ).lower()
    return raw, re.sub(r"\s+", "", raw)


def is_submit_element(tag_name: str, attributes: Mapping[str, str], text: str) -> bool:
    """Decide whether an element looks like a final form-submission control.

    Pure function so it can be unit tested without a browser.

    Rules:
    * Form fields (textarea/select) are never submission controls.
    * ``<input>`` counts via type="submit", a submit-caption ``value`` on
      button-like input types, or submit-like id/name attributes.
    * Any other element with an exact submit-like visible text counts —
      job-board UIs render real buttons as styled div/span/a elements.
    """
    tag = (tag_name or "").lower()
    if tag in _FIELD_TAGS:
        return False

    input_type = (attributes.get("type") or "").lower()
    if tag == "input":
        if input_type == "submit":
            return True
        if input_type in _BUTTON_INPUT_TYPES and (
            attributes.get("value") or ""
        ).strip().lower() in _SUBMIT_TEXTS:
            return True

    raw_haystack, collapsed_haystack = _attr_haystack(attributes)
    if tag in ("button", "input", "div", "span", "a"):
        for hint in _SUBMIT_ATTR_HINTS:
            if hint in raw_haystack or hint in collapsed_haystack:
                return True

    # Exact-text rule last: applies to non-field elements regardless of tag,
    # because custom widgets may use unexpected markup.
    return (text or "").strip().lower() in _SUBMIT_TEXTS


def node_is_submit(node: Any) -> bool:
    """Convenience wrapper applying :func:`is_submit_element` to a DOM node."""
    tag = getattr(node, "tag_name", "") or ""
    text = ""
    getter = getattr(node, "get_all_children_text", None)
    if callable(getter):
        try:
            text = str(getter())
        except Exception:  # noqa: BLE001 — DOM helpers vary across browser-use versions
            text = ""
    attrs = getattr(node, "attributes", None)
    attributes: Mapping[str, str] = attrs if isinstance(attrs, Mapping) else {}
    return is_submit_element(tag, attributes, text)


def should_block_enter(
    keys: str,
    active_tag: str,
    active_type: str = "",
    is_content_editable: bool = False,
) -> bool:
    """Whether an Enter keystroke should be blocked.

    Enter is allowed inside ``textarea`` and ``contenteditable`` elements
    (it inserts a newline). Everywhere else in a form context it risks
    submitting the form, so it is blocked.
    """
    if "enter" not in keys.lower():
        return False
    if is_content_editable:
        return False
    tag = (active_tag or "").lower()
    if tag == "textarea":
        return False
    if tag == "input" and (active_type or "").lower() not in _SINGLE_LINE_INPUT_TYPES:  # noqa: SIM103 -- explicit branches are clearer than negated return
        # Non-text inputs (checkbox, radio, button, etc.) — Enter is not a
        # submission risk there (it toggles/activates the control itself).
        return False
    # Single-line input, select, or any other focused element including
    # body/div when no specific field is focused — block to be safe.
    # Textareas and contenteditables already returned above.
    return True
