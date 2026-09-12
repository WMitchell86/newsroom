"""M0 smoke + safety tests.

Covers M0 acceptance criteria that can be checked locally:
- package imports, config fail-closed defaults, structured logging works,
- no publish/telegram/wordpress symbols exist, no network usage in M0 code.
"""

from __future__ import annotations

import io
import json
import logging

import editor_assistant
from editor_assistant import logging_setup as log_mod
from editor_assistant.config import load_config


def test_package_imports_and_version():
    assert editor_assistant.__version__ == "0.0.1"


def test_config_defaults_are_safe():
    settings = load_config({})
    assert settings.auto_publish is False
    assert settings.dry_run is True
    assert settings.env == "local"


def test_config_auto_publish_cannot_be_enabled_in_m0():
    # Even explicit opt-in must stay disabled: no allow-listed workflow exists.
    for raw in ("1", "true", "TRUE", "yes", "on"):
        assert load_config({"AUTO_PUBLISH": raw}).auto_publish is False


def test_config_dry_run_defaults_true_and_parses_explicit_false():
    assert load_config({}).dry_run is True
    assert load_config({"DRY_RUN": "false"}).dry_run is False
    assert load_config({"DRY_RUN": "garbage"}).dry_run is True  # fail-closed


def test_structured_logging_emits_json_record():
    log_mod.reset_logging_for_tests()
    stream = io.StringIO()
    logger = log_mod.setup_logging("INFO", stream=stream)
    logger.info("m0 smoke", extra={"component": "test"})
    line = stream.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["msg"] == "m0 smoke"
    assert payload["level"] == "INFO"
    assert payload["component"] == "test"
    assert "ts" in payload
    log_mod.reset_logging_for_tests()
    logging.getLogger().handlers.clear()


def test_no_publish_or_external_write_paths_exist():
    """Scan code tokens only (comments/docstrings excluded via tokenize)."""
    import pathlib
    import tokenize

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "editor_assistant"
    forbidden = ("publish", "wordpress", "n8n", "requests", "httpx")
    # Allowed: config.py owns the AUTO_PUBLISH safety flag as data, not behavior;
    # sources/fetcher.py owns the stdlib-only read-only HTTP fetch (urllib) used
    # by M1.2 fetch_bytes — no write/publish capability.
    # NOTE (M1.4B): notify/telegram.py + send_telegram.py are the single
    # allow-listed TEST-channel notification delivery path (dry-run default,
    # --send + DRY_RUN=false + explicit allow-listed chat required). They are
    # intentionally excluded here; delivery-gate tests live in test_telegram*.
    # Match whole identifiers / underscore segments (so `published_at` is fine,
    # but a real `publish(...)` symbol anywhere is flagged).
    allowed = {("config.py", "auto_publish"), ("fetcher.py", "urllib")}
    excluded = {"telegram.py", "send_telegram.py"}
    hits = []
    files = [p for p in sorted(src.glob("*.py")) + sorted((src / "sources").glob("*.py"))]
    files += [p for p in sorted((src / "notify").glob("*.py")) if p.name not in excluded]
    for path in files:
        with open(path, "rb") as fh:
            tokens = tokenize.tokenize(fh.readline)
            for tok in tokens:
                if tok.type != tokenize.NAME:
                    continue
                lowered = tok.string.lower()
                if (path.name, lowered) in allowed:
                    continue
                segments = set(lowered.split("_")) | {lowered}
                for word in forbidden:
                    if word in segments:
                        hits.append(f"{path.name}:{tok.start[0]}: {tok.string}")
    assert hits == [], f"forbidden external-write symbols found: {hits}"
