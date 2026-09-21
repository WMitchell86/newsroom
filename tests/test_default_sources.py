"""M4A.1 default source catalogue tests (offline, no network).

Pin the catalogue contract: unique IDs, the milestone's required IDs present, the
optional sources disabled, and — most importantly — that applying the catalogue
is additive and never overwrites what the editor already owns.
"""

from __future__ import annotations

import pathlib
import tokenize

import pytest

from editor_assistant.workflow import cli
from editor_assistant.workflow import default_sources as D
from editor_assistant.workflow import sources_registry as R

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / "src" / "editor_assistant" / "workflow"

#: The source/collection stack must stay AI/story-free (M4A.1 + M4C PART 24):
#: collecting, storing and reporting raw source items never involves story
#: semantics. M4C moved the story work into explicit modules (below), so this
#: guard keeps its teeth instead of being deleted or worked around by naming.
NEWSROOM_MODULES = (
    WORKFLOW / "default_sources.py",
    WORKFLOW / "blocked_domains.py",
    WORKFLOW / "source_health.py",
    WORKFLOW / "sources_registry.py",
    WORKFLOW / "newsroom_run.py",
    WORKFLOW / "inbox_store.py",
)
AI_TOKENS = (
    "discovery",
    "angles",
    "readiness",
    "drafting",
    "transcriber",
    "clustering",
    "embedding",
    "telegram",
    "new_development",
)

#: M4C story semantics live only in these modules. They may be semantic, but they
#: still may not draft, publish, or reach Telegram/transcripts/generic agents.
M4C_MODULES = (
    WORKFLOW / "publication_identity.py",
    WORKFLOW / "story_store.py",
    WORKFLOW / "story_identity.py",
    WORKFLOW / "story_relation.py",
    WORKFLOW / "workbench" / "newsroom.py",
)
M4C_FORBIDDEN_TOKENS = (
    "telegram",
    "transcriber",
    "publish",
    "wordpress",
    "n8n",
    "requests",
    "httpx",
    "apscheduler",
    "youtube",
)


def _tokens(path):
    with open(path, "rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type == tokenize.NAME:
                yield token.string.lower()


@pytest.mark.parametrize("path", NEWSROOM_MODULES, ids=lambda p: p.name)
def test_no_ai_or_story_identity_tokens_in_the_newsroom_stack(path):
    hits = sorted({token for token in _tokens(path) if token in AI_TOKENS})
    assert hits == [], f"{path.name} grew an AI/story-identity token: {hits}"


@pytest.mark.parametrize("path", M4C_MODULES, ids=lambda p: p.name)
def test_m4c_modules_never_draft_publish_or_reach_other_pipelines(path):
    """Story identity may be semantic; it still stays inside its own boundary."""
    hits = sorted({token for token in _tokens(path) if token in M4C_FORBIDDEN_TOKENS})
    assert hits == [], f"{path.name} grew a forbidden token: {hits}"


@pytest.mark.parametrize("path", NEWSROOM_MODULES, ids=lambda p: p.name)
def test_the_newsroom_stack_stays_one_shot_and_non_publishing(path):
    """No scheduler and no publishing path may appear in the collection stack."""
    tokens = set(_tokens(path))
    forbidden = tokens & {"apscheduler", "schedule", "crontab", "publish", "wordpress", "httpx"}
    assert forbidden == set(), f"{path.name} grew a forbidden token: {sorted(forbidden)}"
    source = path.read_text(encoding="utf-8")
    assert "threading.Timer" not in source and "BackgroundScheduler" not in source


@pytest.fixture
def store(tmp_path):
    return tmp_path / "sources.json"


def test_catalogue_has_unique_ids_and_the_required_set():
    ids = [entry["source_id"] for entry in D.CATALOG]
    assert len(ids) == len(set(ids))
    missing = [sid for sid in D.required_ids() if sid not in ids]
    assert missing == []
    assert all(entry["status"] for entry in D.CATALOG)


def test_catalogue_never_contains_flagman_or_the_own_site():
    text = " ".join(
        f"{e['source_id']} {e.get('url', '')} {e.get('query', '')}" for e in D.CATALOG
    ).lower()
    assert "flagman" not in text
    assert "chernomorie" not in text


def test_optional_sources_are_disabled_and_not_seeded():
    disabled = {e["source_id"] for e in D.CATALOG if e["status"] == "disabled"}
    assert disabled == set(D.OPTIONAL_IDS)
    seeded = {e["source_id"] for e in D.DEFAULT_ENTRIES}
    assert seeded.isdisjoint(disabled)
    assert "burgas-municipal-council" in seeded


def test_catalogue_entries_validate_against_the_registry_schema():
    for entry in D.CATALOG:
        R.validate_entry(entry)  # raises on any schema drift


def test_required_sources_declare_their_publisher_domain():
    """Authority is keyed by the real publisher domain, so the core/daily sources
    must declare one (the broad aggregator deliberately does not)."""
    by_id = D.catalog_by_id()
    aggregators = {sid for sid, entry in by_id.items() if entry["kind"] == "aggregator"}
    missing = [
        sid for sid in D.required_ids() if sid not in aggregators and not by_id[sid].get("domain")
    ]
    assert missing == []
    assert by_id["google-news-burgas-region"]["domain"] == ""  # aggregator, no publisher
    assert by_id["bnr-burgas"]["domain"] == "bnr.bg"
    assert by_id["burgas-municipality"]["domain"] == "burgas.bg"


def test_preview_writes_nothing_and_apply_is_additive_and_idempotent(store):
    preview = R.apply_defaults(path=store, preview=True)
    assert preview["preview"] is True
    assert len(preview["added"]) == len(D.CATALOG)
    assert not store.exists()  # preview performs no write

    first = R.apply_defaults(path=store, preview=False)
    assert len(first["added"]) == len(D.CATALOG)
    assert first["present"] == []

    second = R.apply_defaults(path=store, preview=False)
    assert second["added"] == []
    assert len(second["present"]) == len(D.CATALOG)
    # idempotent: the bytes do not change on a repeated apply
    before = store.read_text(encoding="utf-8")
    R.apply_defaults(path=store, preview=False)
    assert store.read_text(encoding="utf-8") == before


def test_apply_never_changes_or_re_enables_an_editor_owned_entry(store):
    R.add_source(
        path=store,
        source_id="burgas-municipality",
        name="Община Бургас (мое име)",
        kind="official",
        collector="google_news_rss",
        query="Община Бургас",
        priority="low",
        factual_authority=True,
    )
    R.set_status("burgas-municipality", "disabled", path=store)

    result = R.apply_defaults(path=store, preview=False)
    assert "burgas-municipality" in result["present"]
    assert "burgas-municipality" not in result["added"]
    entry = R.read_registry(store)["burgas-municipality"]
    assert entry["name"] == "Община Бургас (мое име)"
    assert entry["priority"] == "low"
    assert entry["status"] == "disabled"  # never silently re-enabled


def test_seed_defaults_uses_the_catalogue(store):
    result = R.seed_defaults(path=store)
    assert "burgas-municipal-council" in result["added"]
    assert "burgasinfo" not in result["added"]  # optional stays out of a new install
    assert R.read_registry(store)["burgas-municipal-council"]["collector"] == "rss"


def test_cli_defaults_preview_and_apply(store, monkeypatch, capsys):
    monkeypatch.setenv("NEWSROOM_SOURCES_PATH", str(store))
    cli.main(["sources", "defaults", "--preview"])
    out = capsys.readouterr().out
    assert "ПРЕДГЛЕД" in out and "добавени" in out
    assert not store.exists()

    cli.main(["sources", "defaults", "--apply"])
    out = capsys.readouterr().out
    assert "ПРИЛОЖЕНИ" in out
    assert len(R.read_registry(store)) == len(D.CATALOG)
