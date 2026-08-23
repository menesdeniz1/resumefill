"""Application settings.

Settings are loaded once from environment variables (optionally via a `.env`
file at the project root) and passed explicitly to every component. Nothing
else in the codebase reads `os.environ` directly, so configuration stays
testable and free of hidden global state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Disable browser-use telemetry before the library is imported anywhere.
# See https://docs.browser-use.com for details.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower()[:1] in ("t", "y", "1")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not a number") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not an integer") from exc


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration."""

    gemini_api_key: str = ""
    default_model: str = "gemini-flash-latest"
    temperature: float = 0.3

    # Agent limits — hard ceilings on cost and runtime.
    max_steps: int = 60
    max_failures: int = 5
    max_actions_per_step: int = 10
    step_delay_seconds: float = 0.0

    # Browser behaviour.
    headless: bool = False
    keep_alive: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    # Filesystem locations.
    log_dir: Path = PROJECT_ROOT / "logs"
    data_dir: Path = PROJECT_ROOT / "data"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def has_api_key(self) -> bool:
        return bool(self.gemini_api_key.strip())

    def default_cv_path(self) -> Path | None:
        """Fallback CV location; None when the file does not exist."""
        candidate = self.data_dir / "cv.txt"
        return candidate if candidate.is_file() else None


def load_settings(env_file: Path | None = None) -> Settings:
    """Build Settings from the process environment (and optional .env file)."""
    load_dotenv(env_file if env_file is not None else PROJECT_ROOT / ".env")
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        default_model=os.getenv("RF_DEFAULT_MODEL", Settings.default_model),
        temperature=_env_float("RF_TEMPERATURE", Settings.temperature),
        max_steps=_env_int("RF_MAX_STEPS", Settings.max_steps),
        max_failures=_env_int("RF_MAX_FAILURES", Settings.max_failures),
        max_actions_per_step=_env_int("RF_MAX_ACTIONS_PER_STEP", Settings.max_actions_per_step),
        step_delay_seconds=_env_float("RF_STEP_DELAY_SECONDS", Settings.step_delay_seconds),
        headless=_env_bool("RF_HEADLESS", Settings.headless),
        keep_alive=_env_bool("RF_KEEP_ALIVE", Settings.keep_alive),
    )
