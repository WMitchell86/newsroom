"""M3B.1 guards: the anti-ban invariants that must not quietly erode.

These are structural checks (source tokens + import graph + CLI parity), not
behavioural ones. They exist so a later change cannot turn the intake into a
scheduler, a drafting path or an editorial authority without failing loudly.
"""

import pathlib
import tokenize

import pytest

from editor_assistant.workflow import cli
from editor_assistant.workflow import intake_run as R

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "editor_assistant" / "workflow"

ANTIBAN_MODULES = (
    "youtube_policy.py",
    "invidious.py",
    "intake_queue.py",
    "intake_run.py",
    "transcriber.py",
)

#: Tokens that would mean an editorial or publishing capability crept in.
FORBIDDEN = ("publish", "wordpress", "requests", "httpx", "drafting")


def _tokens(path):
    with open(path, "rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type == tokenize.NAME:
                yield token.string.lower()


@pytest.mark.parametrize("name", ANTIBAN_MODULES)
def test_no_editorial_or_publishing_tokens_in_the_intake_stack(name):
    hits = [token for token in _tokens(SRC / name) if token in FORBIDDEN]
    assert hits == [], f"{name} grew an editorial/publishing token: {hits}"


def test_there_is_no_scheduler_daemon_anywhere_in_the_intake_stack():
    """The cron entry point is a one-shot process; the repo never schedules."""
    sources = "\n".join((SRC / name).read_text(encoding="utf-8") for name in ANTIBAN_MODULES)
    for forbidden in ("import schedule", "BackgroundScheduler", "threading.Timer", "apscheduler"):
        assert forbidden not in sources


def test_the_transport_layers_do_not_import_the_editorial_stack():
    """invidious/queue/policy are plumbing: no discovery, angles or drafting."""
    for name in ("invidious.py", "intake_queue.py", "youtube_policy.py"):
        source = (SRC / name).read_text(encoding="utf-8")
        for forbidden in ("import discovery", "import angles", "import readiness", "draft"):
            assert forbidden not in source, f"{name} must not depend on {forbidden}"


def test_the_run_loop_takes_the_production_intake_by_default():
    import inspect

    signature = inspect.signature(R.run_once)
    assert signature.parameters["intake_fn"].default is None
    assert R.default_intake.__module__.endswith("intake_run")


def test_cli_batch_run_goes_through_the_shared_run_service(monkeypatch):
    captured = {}

    def fake_run_once(**kwargs):
        captured.update(kwargs)
        return {
            "exit_code": R.EXIT_OK,
            "note": "stub",
            "stats": {},
            "entries": [],
            "breaker": False,
            "jitter_slept_s": 0,
        }

    monkeypatch.setattr(R, "run_once", fake_run_once)
    monkeypatch.setattr(R, "finish_run", lambda result, **kwargs: {})
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["youtube-batch", "run", "--no-jitter", "--cap", "2"])
    assert exit_info.value.code == R.EXIT_OK
    assert captured["cap"] == 2
    assert captured["cron"] is False
    assert captured["jev_shadow_enabled"] is False


def test_both_intake_paths_share_one_run_lock():
    """Interactive and cron must not be two concurrency stories (see Q5)."""
    import inspect

    interactive = inspect.getsource(cli.cmd_youtube_intake)
    assert "acquire_lock" in interactive and "release_lock" in interactive
    # The batch path is locked inside run_once, so it must keep going through it.
    assert "run_once" in inspect.getsource(cli.cmd_youtube_batch)
    assert "acquire_lock" in inspect.getsource(R.run_once)


def test_cli_interactive_intake_refuses_when_the_run_lock_is_held(monkeypatch):
    from editor_assistant.workflow import intake as intake_mod

    attempted = []
    monkeypatch.setattr(R, "acquire_lock", lambda **kwargs: False)
    monkeypatch.setattr(intake_mod, "intake_youtube", lambda *a, **k: attempted.append(a) or {})

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["youtube-intake", "https://youtu.be/dQw4w9WgXcQ", "--skip-jev-shadow"])

    assert exit_info.value.code == R.EXIT_LOCKED
    assert attempted == []  # no request was made while cron holds the lock


def test_cli_interactive_intake_takes_and_releases_the_run_lock(monkeypatch):
    from editor_assistant.workflow import intake as intake_mod

    events = []
    monkeypatch.setattr(
        R, "acquire_lock", lambda **kwargs: events.append(("acquire", kwargs)) or True
    )
    monkeypatch.setattr(R, "release_lock", lambda **kwargs: events.append(("release", kwargs)))

    def fake_intake(url, **kwargs):
        events.append(("intake", url))
        return {
            "outcome": "NO_PUBLISHABLE_ANGLE",
            "original_url": url,
            "stages": {},
            "video": {},
            "analysis": {},
            "artifacts": {},
        }

    monkeypatch.setattr(intake_mod, "intake_youtube", fake_intake)
    cli.main(["youtube-intake", "https://youtu.be/dQw4w9WgXcQ", "--skip-jev-shadow"])

    assert [event[0] for event in events] == ["acquire", "intake", "release"]
    assert events[0][1]["stale_after_s"] > 0  # the policy's staleness, not a hardcoded one


def test_cli_interactive_intake_releases_the_lock_even_on_failure(monkeypatch):
    from editor_assistant.workflow import intake as intake_mod

    released = []
    monkeypatch.setattr(R, "acquire_lock", lambda **kwargs: True)
    monkeypatch.setattr(R, "release_lock", lambda **kwargs: released.append(True))

    def boom(*args, **kwargs):
        raise RuntimeError("killed by operator")

    monkeypatch.setattr(intake_mod, "intake_youtube", boom)
    with pytest.raises(RuntimeError):
        cli.main(["youtube-intake", "https://youtu.be/dQw4w9WgXcQ", "--skip-jev-shadow"])

    assert released == [True]


def test_cli_cron_flag_enables_the_startup_jitter(monkeypatch):
    captured = {}

    def fake_run_once(**kwargs):
        captured.update(kwargs)
        return {
            "exit_code": R.EXIT_OK,
            "note": "",
            "stats": {},
            "entries": [],
            "breaker": False,
            "jitter_slept_s": 0,
        }

    monkeypatch.setattr(R, "run_once", fake_run_once)
    monkeypatch.setattr(R, "finish_run", lambda result, **kwargs: {})
    with pytest.raises(SystemExit):
        cli.main(["youtube-batch", "run", "--cron"])
    assert captured["cron"] is True
