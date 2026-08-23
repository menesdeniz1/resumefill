"""browser-use Tools with code-enforced submission blocking."""

from __future__ import annotations

import json

from browser_use import ActionResult, Tools
from browser_use.tools.views import ClickElementActionIndexOnly, SendKeysAction

from resumefill.agent.safety import node_is_submit, should_block_enter

_BLOCK_MESSAGE = (
    "BLOCKED: that element looks like a final form SUBMISSION control "
    "(text/attributes: {desc!r}). This agent must never submit the application — "
    "the user reviews and submits manually. If more fields remain on this page, "
    "fill them; otherwise stop and finish."
)

_ENTER_BLOCK_MESSAGE = (
    "BLOCKED: Enter key in single-line field (focused: {desc}). "
    "Enter inside textareas is allowed, but Enter in single-line inputs can submit "
    "the form. Use Tab or click to move to the next field instead."
)


class GuardedTools(Tools):
    """``Tools`` with code-enforced guards.

    * ``click`` refuses submit-like controls.
    * ``send_keys`` refuses Enter in single-line fields (textareas stay allowed).

    Both work by re-registering the built-in action with a wrapper that
    inspects the target before delegating. ``_builtin_*`` attributes are
    stored so tests can substitute spies.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        registry = self.registry
        self._builtin_click = registry.registry.actions["click"].function
        self._builtin_send_keys = registry.registry.actions["send_keys"].function

        @registry.action("Click element by index.", param_model=ClickElementActionIndexOnly)
        async def click(params: ClickElementActionIndexOnly, browser_session):  # noqa: WPS430
            node = await browser_session.get_element_by_index(params.index)
            if node is not None and node_is_submit(node):
                from browser_use.tools.utils import get_click_description

                return ActionResult(error=_BLOCK_MESSAGE.format(desc=get_click_description(node)))
            return await self._builtin_click(params=params, browser_session=browser_session)

        assert registry.registry.actions["click"].function is not self._builtin_click

        @registry.action("Send keys", param_model=SendKeysAction)
        async def send_keys(params: SendKeysAction, browser_session):  # noqa: WPS430
            if "enter" in params.keys.lower():
                desc = "unknown element"
                should_block = False
                try:
                    cdp_session = await browser_session.get_or_create_cdp_session()
                    result = await cdp_session.cdp_client.send.Runtime.evaluate(
                        params={
                            "expression": (
                                "(() => { const el = document.activeElement; if (!el) return JSON.stringify({tag:'',type:'',ce:false});"
                                " return JSON.stringify({tag: el.tagName||'', type: el.getAttribute('type')||'', ce: !!el.isContentEditable, id: el.id||'', name: el.name||''}); })()"
                            ),
                            "returnByValue": True,
                            "awaitPromise": True,
                        },
                        session_id=cdp_session.session_id,
                    )
                    raw = result.get("result", {}).get("value")
                    if isinstance(raw, str):
                        info = json.loads(raw)
                        tag = str(info.get("tag", ""))
                        typ = str(info.get("type", ""))
                        ce = bool(info.get("ce", False))
                        desc = f"<{tag.lower()} type={typ!r} id={info.get('id','')!r}>"
                        should_block = should_block_enter(params.keys, tag, typ, ce)
                    else:
                        # Unexpected shape — fail open to avoid breaking textarea Enter
                        should_block = False
                except Exception:  # noqa: BLE001 — CDP unavailable, fail open
                    should_block = False
                if should_block:
                    return ActionResult(error=_ENTER_BLOCK_MESSAGE.format(desc=desc))
            return await self._builtin_send_keys(params=params, browser_session=browser_session)

        assert registry.registry.actions["send_keys"].function is not self._builtin_send_keys
