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


# ── helpers for send_keys guard ──────────────────────────────────────────────

class FakeRuntime:
    def __init__(self, value: str):
        self._value = value

    async def evaluate(self, params=None, session_id=None):  # noqa: ARG002
        return {"result": {"value": self._value}}


class FakeSend:
    def __init__(self, value: str):
        self.Runtime = FakeRuntime(value)


class FakeCdpClient:
    def __init__(self, value: str):
        self.send = FakeSend(value)


class FakeCdpSession:
    def __init__(self, value: str):
        self.cdp_client = FakeCdpClient(value)
        self.session_id = "test-session"


class FakeSessionWithCdp(FakeSession):
    def __init__(self, node, cdp_value: str):
        super().__init__(node)
        self._cdp_value = cdp_value

    async def get_or_create_cdp_session(self):
        return FakeCdpSession(self._cdp_value)


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
    click_action = plain.registry.registry.actions["click"]
    assert click_action.description == "Click element by index."
    assert click_action.param_model is not None
    send_keys_action = plain.registry.registry.actions["send_keys"]
    assert send_keys_action.description == "Send keys"
    assert send_keys_action.param_model is not None


@pytest.mark.asyncio
async def test_send_keys_non_enter_delegates():
    from browser_use.tools.views import SendKeysAction

    tools = GuardedTools()
    calls: list[dict] = []

    async def spy(**kwargs):
        calls.append(kwargs)
        return {"error": None}

    tools._builtin_send_keys = spy
    handler = tools.registry.registry.actions["send_keys"].function
    session = FakeSessionWithCdp(None, '{"tag":"INPUT","type":"text","ce":false}')
    result = await handler(params=SendKeysAction(keys="Tab"), browser_session=session)
    assert result is not None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_keys_enter_in_textarea_delegates():
    from browser_use.tools.views import SendKeysAction

    tools = GuardedTools()
    calls: list[dict] = []

    async def spy(**kwargs):
        calls.append(kwargs)
        return {"error": None}

    tools._builtin_send_keys = spy
    handler = tools.registry.registry.actions["send_keys"].function
    session = FakeSessionWithCdp(None, '{"tag":"TEXTAREA","type":"","ce":false}')
    await handler(params=SendKeysAction(keys="Enter"), browser_session=session)
    assert len(calls) == 1  # allowed in textarea


@pytest.mark.asyncio
async def test_send_keys_enter_in_single_line_input_blocked():
    from browser_use.tools.views import SendKeysAction

    tools = GuardedTools()
    calls: list[dict] = []

    async def spy(**kwargs):
        calls.append(kwargs)
        return {"error": None}

    tools._builtin_send_keys = spy
    handler = tools.registry.registry.actions["send_keys"].function
    session = FakeSessionWithCdp(None, '{"tag":"INPUT","type":"text","ce":false}')
    result = await handler(params=SendKeysAction(keys="Enter"), browser_session=session)
    assert result.error is not None and "BLOCKED" in result.error
    assert calls == []


@pytest.mark.asyncio
async def test_send_keys_cdp_failure_fails_open():
    from browser_use.tools.views import SendKeysAction

    tools = GuardedTools()
    calls: list[dict] = []

    async def spy(**kwargs):
        calls.append(kwargs)
        return {"error": None}

    tools._builtin_send_keys = spy
    handler = tools.registry.registry.actions["send_keys"].function

    class BrokenSession(FakeSession):
        async def get_or_create_cdp_session(self):
            raise RuntimeError("CDP unavailable")

    session = BrokenSession(None)
    await handler(params=SendKeysAction(keys="Enter"), browser_session=session)
    assert len(calls) == 1  # fail open — don't break textarea Enter
