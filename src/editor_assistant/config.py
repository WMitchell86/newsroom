"""M0 config loader — fail-closed safety defaults, no secrets, no network.

Safety contract (AI_HARNESS_EDITOR_ASSISTANT.md §2.1, §15):
- AUTO_PUBLISH defaults to False. There is no publish path in M0, so even an
  explicit env opt-in must NOT enable publishing yet (no allow-listed workflow
  exists). The loader parses the env var honestly but forces False until a
  future milestone introduces an explicit allow-listed workflow.
- DRY_RUN defaults to True for all future external writes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    """Strict bool parsing: unknown/empty values fall back to `default` (fail-closed)."""
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


@dataclass(frozen=True)
class Settings:
    env: str = "local"
    log_level: str = "INFO"
    auto_publish: bool = False
    dry_run: bool = True


def load_config(environ: dict[str, str] | None = None) -> Settings:
    """Load settings from environment mapping (defaults to os.environ).

    No secrets are required in M0. No network calls. Pure deterministic parsing.
    """
    env = environ if environ is not None else os.environ
    requested = _parse_bool(env.get("AUTO_PUBLISH"), default=False)
    # M0 hard guard: no allow-listed publish workflow exists yet, so publishing
    # stays disabled regardless of env. A future milestone may relax this for a
    # specific, human-approved, reversible workflow only. `requested` is parsed
    # (callers may log it) but never honored in M0.
    auto_publish = False
    _ = requested
    return Settings(
        env=(env.get("ENV") or "local").strip().lower() or "local",
        log_level=(env.get("LOG_LEVEL") or "INFO").strip().upper() or "INFO",
        auto_publish=auto_publish,
        dry_run=_parse_bool(env.get("DRY_RUN"), default=True),
    )


def get_settings() -> Settings:
    """Convenience wrapper reading the real process environment."""
    return load_config(None)
