"""browser-use Tools with code-enforced submission blocking."""

from __future__ import annotations

from browser_use import ActionResult, Tools
from browser_use.tools.views import ClickElementActionIndexOnly

from resumefill.agent.safety import node_is_submit

_BLOCK_MESSAGE = (
    "BLOCKED: that element looks like a final form SUBMISSION control "
    "(text/attributes: {desc!r}). This agent must never submit the application — "
    "the user reviews and submits manually. If more fields remain on this page, "
    "fill them; otherwise stop and finish."
)


class GuardedTools(Tools):
    """``Tools`` whose ``click`` action refuses to click submit controls.

    Works by re-registering the built-in ``click`` action (the registry
    overwrites entries by name) with a wrapper that inspects the target
    element first and delegates to the built-in implementation when safe.
    ``_builtin_click`` is stored as an attribute so tests can substitute a
    spy instead of a real browser implementation.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        registry = self.registry
        self._builtin_click = registry.registry.actions["click"].function

        @registry.action("Click element by index.", param_model=ClickElementActionIndexOnly)
        async def click(params: ClickElementActionIndexOnly, browser_session):  # noqa: WPS430
            node = await browser_session.get_element_by_index(params.index)
            if node is not None and node_is_submit(node):
                from browser_use.tools.utils import get_click_description

                return ActionResult(error=_BLOCK_MESSAGE.format(desc=get_click_description(node)))
            return await self._builtin_click(params=params, browser_session=browser_session)

        assert registry.registry.actions["click"].function is not self._builtin_click
