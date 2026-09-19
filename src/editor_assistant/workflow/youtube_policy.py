"""YouTube intake anti-ban and pacing policy (M3B.1).

Ideas borrowed from a sibling project (*youtube scripts downloader / ytvault*).
The useful lesson there is that YouTube pushback is managed by three things, not
by clever parsing:

* **pacing** - one video at a time, a random pause between them, a small nightly
  cap, and a random startup delay so a nightly job has no fixed signature;
* **identity** - a browser-like request (cookie file, TLS impersonation,
  non-default player clients) instead of a bare Python client;
* **stopping** - a soft block (429 / bot check) must halt the run and cool the
  IP down, because pushing through turns it into a hard ban.

This module only holds and validates the knobs. Behaviour lives in
`transcriber` (per-request identity, block classification, fallback) and
`intake_run` (run-level pacing, lock, circuit breaker).

Defaults are deliberately conservative. Everything is environment-driven and
`load_policy(env)` takes an explicit mapping so tests never touch `os.environ`.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace

#: Backoff ladder for a failed video, in seconds: 15m -> 1h -> 6h -> 24h.
BACKOFF_SECONDS = (900, 3600, 21600, 86400)

#: Player clients community-reported to pass checks the default web client
#: fails. Rotated per video, first success wins.
DEFAULT_PLAYER_CLIENTS = ("tv_simply", "web_safari")

#: Public Invidious instances (docs.invidious.io/instances). Only used *after*
#: YouTube has pushed back: the instance proxies the request, so this IP stops
#: touching YouTube for the rest of the run.
DEFAULT_INVIDIOUS_INSTANCES = (
    "https://inv.nadeko.net",
    "https://yewtu.be",
    "https://invidious.nerdvpn.de",
)

#: Defaults. Conservative on purpose - do not loosen without a scope decision.
DEFAULTS = {
    "nightly_cap": 5,
    "delay_min_s": 60,
    "delay_max_s": 120,
    "startup_jitter_min_s": 600,  # 10 min
    "startup_jitter_max_s": 2400,  # 40 min
    "max_attempts": 5,
    "block_cooldown_h": 12,
    "lock_stale_s": 6 * 3600,
    "timeout_s": 180,
    # OFF by default: the fallback contacts an unrelated third party (public
    # Invidious instances) and sends the video id to it, and the live probe on
    # 2026-09-19 found 0 of 9 instances serving captions. An operator must opt
    # in explicitly - see BACKLOG.md (M3B.1 deferred).
    "fallback_enabled": False,
    "impersonate": "",  # off by default: needs the optional curl-cffi extra
}

#: Upper bounds, so a hand-edited .env cannot turn pacing into hammering.
MAX_NIGHTLY_CAP = 50
MAX_DELAY_S = 900
MAX_JITTER_S = 6 * 3600
MAX_ATTEMPTS = 20
MAX_COOLDOWN_H = 72

ENV_PREFIX = "YOUTUBE_"


def _note(notes, message):
    """Collect an operator-visible policy adjustment (never raise on bad env)."""
    if notes is not None:
        notes.append(message)


def _int(env, key, default, *, minimum=0, maximum=None, notes=None):
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        _note(notes, f"{key}={raw!r} is not an integer -> using the default {default}")
        return default
    if value < minimum:
        _note(notes, f"{key}={value} is below the minimum {minimum} -> using the default {default}")
        return default
    if maximum is not None and value > maximum:
        _note(notes, f"{key}={value} is above the safety maximum {maximum} -> clamped to {maximum}")
        return maximum
    return value


def _bool(env, key, default):
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _csv(env, key, default):
    """Comma-separated list; falls back to the default when unset/empty."""
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return tuple(default)
    parts = tuple(part.strip() for part in str(raw).split(",") if part.strip())
    return parts or tuple(default)


@dataclass(frozen=True)
class IntakePolicy:
    """Pacing/identity/stop rules for one intake run."""

    nightly_cap: int = DEFAULTS["nightly_cap"]
    delay_min_s: int = DEFAULTS["delay_min_s"]
    delay_max_s: int = DEFAULTS["delay_max_s"]
    startup_jitter_min_s: int = DEFAULTS["startup_jitter_min_s"]
    startup_jitter_max_s: int = DEFAULTS["startup_jitter_max_s"]
    max_attempts: int = DEFAULTS["max_attempts"]
    block_cooldown_h: int = DEFAULTS["block_cooldown_h"]
    lock_stale_s: int = DEFAULTS["lock_stale_s"]
    timeout_s: int = DEFAULTS["timeout_s"]
    fallback_enabled: bool = DEFAULTS["fallback_enabled"]
    player_clients: tuple = DEFAULT_PLAYER_CLIENTS
    cookies_file: str = ""
    proxy: str = ""
    impersonate: str = DEFAULTS["impersonate"]
    invidious_instances: tuple = DEFAULT_INVIDIOUS_INSTANCES
    #: Operator-visible adjustments made while loading (clamped / defaulted
    #: env values, inverted ranges). Empty on a clean environment. Never a
    #: secret: only key names and numbers, never a value like a proxy URL.
    warnings: tuple = ()

    def __post_init__(self):
        # Normalize a hand-edited policy: never let min > max reach random.randint.
        notes = list(self.warnings)
        if self.delay_min_s > self.delay_max_s:
            notes.append(
                f"delay_min_s={self.delay_min_s} > delay_max_s={self.delay_max_s} -> using the max"
            )
            object.__setattr__(self, "delay_min_s", self.delay_max_s)
        if self.startup_jitter_min_s > self.startup_jitter_max_s:
            notes.append(
                f"startup_jitter_min_s={self.startup_jitter_min_s} > "
                f"startup_jitter_max_s={self.startup_jitter_max_s} -> using the max"
            )
            object.__setattr__(self, "startup_jitter_min_s", self.startup_jitter_max_s)
        if len(notes) != len(self.warnings):
            object.__setattr__(self, "warnings", tuple(notes))

    def as_dict(self):
        return asdict(self)

    def describe(self):
        """One-line, secret-free summary of what this run will actually use."""
        cookies = self.cookies_file or ""
        cookie_state = (
            "OK" if cookies and os.path.isfile(cookies) else ("INVALID" if cookies else "not set")
        )
        return (
            f"cookies: {cookie_state} · proxy: {'set' if self.proxy else 'none'} · "
            f"clients: {', '.join(self.player_clients) or 'default'} · "
            f"impersonate: {self.impersonate or 'off'} · "
            f"fallback: {'on' if self.fallback_enabled else 'off'}"
        )

    def with_cookies(self, value):
        return replace(self, cookies_file=value or "")

    def with_proxy(self, value):
        return replace(self, proxy=value or "")

    def with_impersonate(self, value):
        return replace(self, impersonate=value or "")


def load_policy(env=None) -> IntakePolicy:
    """Build an `IntakePolicy` from environment values (safe defaults).

    A hand-edited value is never trusted blindly: out-of-range and malformed
    values fall back to the safe default and are reported in `warnings`, so a
    silent clamp cannot make the operator believe the run used their number.
    """
    env = os.environ if env is None else env
    key = lambda name: ENV_PREFIX + name
    notes = []
    return IntakePolicy(
        nightly_cap=_int(
            env,
            key("NIGHTLY_CAP"),
            DEFAULTS["nightly_cap"],
            minimum=0,
            maximum=MAX_NIGHTLY_CAP,
            notes=notes,
        ),
        delay_min_s=_int(
            env,
            key("DELAY_MIN_S"),
            DEFAULTS["delay_min_s"],
            minimum=0,
            maximum=MAX_DELAY_S,
            notes=notes,
        ),
        delay_max_s=_int(
            env,
            key("DELAY_MAX_S"),
            DEFAULTS["delay_max_s"],
            minimum=0,
            maximum=MAX_DELAY_S,
            notes=notes,
        ),
        startup_jitter_min_s=_int(
            env,
            key("STARTUP_JITTER_MIN_S"),
            DEFAULTS["startup_jitter_min_s"],
            maximum=MAX_JITTER_S,
            notes=notes,
        ),
        startup_jitter_max_s=_int(
            env,
            key("STARTUP_JITTER_MAX_S"),
            DEFAULTS["startup_jitter_max_s"],
            maximum=MAX_JITTER_S,
            notes=notes,
        ),
        max_attempts=_int(
            env,
            key("MAX_ATTEMPTS"),
            DEFAULTS["max_attempts"],
            minimum=1,
            maximum=MAX_ATTEMPTS,
            notes=notes,
        ),
        block_cooldown_h=_int(
            env,
            key("BLOCK_COOLDOWN_H"),
            DEFAULTS["block_cooldown_h"],
            minimum=1,
            maximum=MAX_COOLDOWN_H,
            notes=notes,
        ),
        lock_stale_s=_int(
            env, key("LOCK_STALE_S"), DEFAULTS["lock_stale_s"], minimum=60, notes=notes
        ),
        timeout_s=_int(env, key("TIMEOUT_S"), DEFAULTS["timeout_s"], minimum=30, notes=notes),
        fallback_enabled=_bool(env, key("FALLBACK"), DEFAULTS["fallback_enabled"]),
        player_clients=_csv(env, key("PLAYER_CLIENTS"), DEFAULT_PLAYER_CLIENTS),
        cookies_file=(env.get(key("COOKIES_FILE")) or "").strip(),
        proxy=(env.get(key("PROXY")) or "").strip(),
        impersonate=(env.get(key("IMPERSONATE")) or DEFAULTS["impersonate"]).strip(),
        invidious_instances=_csv(env, key("INVIDIOUS_INSTANCES"), DEFAULT_INVIDIOUS_INSTANCES),
        warnings=tuple(notes),
    )


def backoff_seconds(attempts) -> int:
    """Backoff for the Nth failed attempt (1-based), capped at the ladder end."""
    index = max(int(attempts or 1), 1) - 1
    return BACKOFF_SECONDS[min(index, len(BACKOFF_SECONDS) - 1)]
