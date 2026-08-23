"""GuardedTools registry replacement and blocking behaviour (no browser needed)."""

from __future__ import annotations

import pytest
from browser_use.tools.views import ClickElementActionIndexOnly

from resumefill.agent.tools import GuardedTools


class FakeNode:
    def __init__(self, tag_name, attributes=None, text=""):
        self.tag_name = tag_name
        self.attributes = attributes or {}
        self._text = text

    def get_all_children_text(self):
        return self._text


class FakeSession:
    def __init__(self, node):
        self.node = node
        self.lookups: list[int] = []

    async def get_element_by_index(self, index):
        self.lookups.append(index)
        return self.node


def _make_tools_with_spy():
    """GuardedTools whose built-in click is replaced by a recording spy."""
    tools = GuardedTools()
    calls: list[dict] = []

    async def spy(**kwargs):
        calls.append(kwargs)
        return {"error": None, "extracted_content": "clicked"}

    tools._builtin_click = spy
    handler = tools.registry.registry.actions["click"].function
    return tools, handler, calls


@pytest.mark.asyncio
async def test_click_action_is_replaced_and_blocks_submit():
    tools = GuardedTools()
    handler = tools.registry.registry.actions["click"].function

    # Spy must NOT be invoked for submit-looking nodes.
    calls: list[dict] = []

    async def spy(**kwargs):
        calls.append(kwargs)
        return {"error": None}

    tools._builtin_click = spy

    session = FakeSession(FakeNode("button", {}, "Submit Application"))
    result = await handler(params=ClickElementActionIndexOnly(index=5), browser_session=session)

    assert result.error is not None and "BLOCKED" in result.error
    assert session.lookups == [5]
    assert calls == []


@pytest.mark.asyncio
async def test_benign_click_delegates_to_builtin():
    _, handler, calls = _make_tools_with_spy()

    session = FakeSession(FakeNode("button", {}, "Next"))
    params = ClickElementActionIndexOnly(index=7)
    await handler(params=params, browser_session=session)

    assert len(calls) == 1
    assert calls[0]["params"] is params
    assert calls[0]["browser_session"] is session


@pytest.mark.asyncio
async def test_missing_node_delegates_like_builtin():
    _, handler, calls = _make_tools_with_spy()

    session = FakeSession(None)  # element not found on page
    await handler(params=ClickElementActionIndexOnly(index=3), browser_session=session)
    assert len(calls) == 1  # decision left to the built-in implementation


def test_registry_metadata_unchanged():
    plain = GuardedTools()
    action = plain.registry.registry.actions["click"]
    assert action.description == "Click element by index."
    assert action.param_model is not None
