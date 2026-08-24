"""Ctrl+C behaviour: first press = graceful stop, second press = force kill.

Streamlit/browser-use teardown can hang on non-daemon threads after a run;
users should never have to close the terminal to regain control.
"""

from __future__ import annotations

import contextlib
import os
import signal

_state = {"count": 0}


def install_double_ctrl_c_force_exit() -> None:
    """Install a SIGINT handler usable from any entry point."""

    def _handler(signum, frame):  # noqa: ARG001 — signal API
        _state["count"] += 1
        if _state["count"] >= 2:
            print("\nForce exit.", flush=True)
            os._exit(130)
        raise KeyboardInterrupt  # let the framework shut down gracefully

    # Not the main thread (or unsupported platform) — skip silently.
    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGINT, _handler)
