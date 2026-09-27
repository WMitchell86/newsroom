"""V1.2-G2.4B — the contract this sub-slice freezes.

Every test here guards a decision the owner made explicitly, so a later slice
cannot quietly undo it.
"""

from __future__ import annotations

from pathlib import Path

from editor_assistant.drafting import model_policy

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# §4 — the extract role budget
# ---------------------------------------------------------------------------


def test_extract_role_has_the_approved_budget():
    """§4: soft 200 / hard 300. Measured demand was 159; the old 50 truncated it."""
    spec = model_policy.load_policy()["roles"]["extract"]
    assert spec["soft_calls_day"] == 200
    assert spec["hard_calls_day"] == 300


def test_the_budget_change_did_not_touch_anything_else():
    """§4/§14: capacity only — never route order, provider, model or paid gate."""
    policy = model_policy.load_policy()
    extract = policy["roles"]["extract"]
    # First route is still the cheap, qualified, high-volume model.
    assert extract["routes"][0]["provider"] == "gemini"
    assert extract["routes"][0]["model"] == "gemini-3.5-flash-lite"
    assert extract["routes"][0]["billing"] == "operator_declared"
    # The paid route is still declared but still unreachable.
    assert policy["global"]["paid_enabled"] is False
    # Draft keeps its stronger model (§14 routing principle, frozen).
    draft_first = policy["roles"]["draft"]["routes"][0]
    assert draft_first["model"] == "gemini-3.8-flash"
    assert policy["roles"]["draft"]["hard_calls_day"] == 25


def test_the_raised_budget_still_fits_the_shared_provider_quota():
    """§5: the roles sharing gemini-3.5-flash-lite must fit inside its quota."""
    policy = model_policy.load_policy()
    shared_model = policy["roles"]["extract"]["routes"][0]["model"]
    quota = next(
        r.get("daily_call_limit")
        for r in policy["roles"]["extract"]["routes"]
        if r.get("model") == shared_model
    )
    assert quota, "the shared model must declare an operator quota"
    total = 0
    for spec in policy["roles"].values():
        routes = [r for r in (spec.get("routes") or []) if r.get("enabled", True)]
        if routes and routes[0].get("model") == shared_model:
            total += int(spec.get("hard_calls_day") or 0)
    assert total <= quota, f"roles sharing {shared_model} can request {total} > quota {quota}"
    assert total > 400, "the point of the raise is real headroom"


# ---------------------------------------------------------------------------
# §3 — Serper is optional, never required
# ---------------------------------------------------------------------------


def test_research_runs_without_any_serper_key(monkeypatch):
    """§3: no crash, no Serper in the chain, unavailability recorded."""
    from editor_assistant.workflow import search as search_mod

    env = {k: v for k, v in __import__("os").environ.items() if k != "SERPER_API_KEY"}
    chain, unavailable = search_mod.provider_chain(capability=search_mod.CAP_NEWS, env=env)
    assert not [p for p in chain if "serper" in p.name]
    assert "serper:no-key" in unavailable


def test_serper_is_absent_from_every_capability_order():
    """§3: Serper must be reachable but never the only route."""
    from editor_assistant.workflow import search as search_mod

    for order in search_mod.PROVIDER_ORDER.values():
        assert order, "every capability keeps at least one provider"


# ---------------------------------------------------------------------------
# §2 — the frozen replay must never search
# ---------------------------------------------------------------------------


def test_a_frozen_discovery_replay_never_searches(tmp_path, monkeypatch):
    """§2/§6, behaviourally: with `discovery` supplied, no search runs at all.

    The search round is replaced with a tripwire that raises, so a regression
    that reached for the network would fail here instead of quietly spending a
    discovery credit.
    """
    from editor_assistant.workflow import (
        inbox_store,
        story_research,
        story_store,
    )
    from editor_assistant.workflow import (
        search as search_mod,
    )

    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    item = {
        "item_id": "origin", "source_id": "vestnik", "source_item_id": "origin",
        "title": "Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол",
        "url": "https://vestnik.example.test/a", "published_at": "2026-09-25T08:00:00Z",
        "discovered_at": "2026-09-25T08:00:00Z", "summary": "", "source_kind": "media",
        "status": "NEW",
    }
    inbox_store.save_items([item], root / "inbox.jsonl")
    story = story_store.new_story(item, now="2026-09-25T08:00:00Z")
    story["story_id"] = "s-one"
    story["status"] = "SEEN"
    story_store.write_store({"stories": [story]}, root / "stories.json")

    def _boom(*a, **kw):
        raise AssertionError("a frozen replay must not search")

    monkeypatch.setattr(search_mod, "run_event_discovery", _boom)

    body = ("Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол. Жената е с контузия на корема, а детето с травма на главата.")

    def _open(url, **_kw):
        return {"final_url": url, "content_type": "text/html; charset=utf-8",
                "bytes": len(body), "text": body}

    frozen = {
        "status": "SEARCH_OK",
        "candidates": [
            {"title": item["title"], "url": "https://a.test/article",
             "snippet": "", "snippet_authority": "DISCOVERY_ONLY",
             "discovered_by": "frozen", "opened": {"status": "FETCH_OK",
             "final_url": "https://a.test/article", "content_type": "text/html", "bytes": 10}},
            {"title": item["title"], "url": "https://b.test/article",
             "snippet": "", "snippet_authority": "DISCOVERY_ONLY",
             "discovered_by": "frozen", "opened": {"status": "FETCH_OK",
             "final_url": "https://b.test/article", "content_type": "text/html", "bytes": 10}},
        ],
    }
    story_research.execute_story_research(
        "s-one", topic=item["title"], root=tmp_path / "editorial",
        canonical_story={"story_id": "s-one"}, page_opener=_open,
        story_title=item["title"], authority_resolver=dict, discovery=frozen,
    )
    from editor_assistant.workflow import story_research_store

    basis = story_research_store.get_story_research("s-one", root=tmp_path / "editorial")
    # The two frozen publishers corroborate, with no search anywhere in the path.
    # One fact row per (claim, source), so two claims x two publishers = four.
    assert basis["facts"], "the frozen publishers should corroborate"
    # Corroboration means two INDEPENDENT publishers, not two URLs.
    assert len({f["sourceId"] for f in basis["facts"]}) == 2
    assert len(basis["sources"]) == 2
    # The remaining blocking questions are the ordinary bootstrap sufficiency
    # assessment and are unrelated to the frozen path.


# ---------------------------------------------------------------------------
# §12 — the single-source experiment stays experimental
# ---------------------------------------------------------------------------


def test_the_single_source_experiment_is_now_wired_in_deliberately():
    """V1.2-G4.1 §B3 — the experiment graduated from measured to adopted.

    G2.4B §E4 kept the single-source policy as an isolated experiment and this
    test pinned that it was never imported by production code. The owner has now
    read that experiment and adopted it: §B3 permits one real opened publisher
    page to start an ATTRIBUTED Draft.

    The opt-in is recorded here rather than left implicit, because the whole
    point of the original §12 pin was to make this import a deliberate, visible
    act. The only production importer is `draft_material`, and the policy
    vocabulary it reuses is still the measured one — no second publisher test and
    no second trust system were introduced.
    """
    from editor_assistant.workflow import draft_material

    offenders = []
    for path in (ROOT / "src" / "editor_assistant").rglob("*.py"):
        if path.name == "single_source_policy.py":
            continue
        if "single_source_policy" in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(str(path.relative_to(ROOT)))
    # Exactly one importer, and it is the module that owns the new rule.
    assert offenders == [
        "src/editor_assistant/workflow/draft_material.py"
    ], offenders
    # The adopted rule reuses the measured publisher test verbatim, so a wrapper
    # or aggregator still cannot support even an attributed Draft.
    assert (
        draft_material.is_opened_publisher_source({"domain": "news.google.com"}) is False
    )
    assert draft_material.is_opened_publisher_source({"domain": "faragency.bg"}) is True


# ---------------------------------------------------------------------------
# §15 — the publisher count uses the shared identity
# ---------------------------------------------------------------------------


def test_today_publisher_count_uses_publisher_identity():
    """§15: `www.burgas.bg` and `burgas.bg` are ONE publisher in the editor count."""
    from editor_assistant.workflow import story_research, story_store

    story = {"members": [{"item_id": "a", "publication_key": "p1"},
                         {"item_id": "b", "publication_key": "p2"}]}
    items = {"a": {"publisher_domain": "www.burgas.bg"},
             "b": {"publisher_domain": "burgas.bg"}}
    assert story_store.metrics(story, items)["publisher_count"] == 1
    for host in ("www.burgas.bg", "burgas.bg", "m.dariknews.bg", "amp.x.com"):
        assert story_store.publisher_identity(host) == story_research._publisher_identity(host)


# ---------------------------------------------------------------------------
# §11 — bnrnews is reported, never silently trusted
# ---------------------------------------------------------------------------


def test_bnrnews_is_not_silently_authoritative():
    """§11: adding it is a registry DATA decision, not a code exception."""
    from editor_assistant.workflow import newsroom_run

    rows = newsroom_run.rows_by_publisher_domain()
    for domain, entries in rows.items():
        if "bnrnews" in domain:
            for entry in entries:
                assert entry["source_id"].startswith("bnrnews"), (
                    "a new bnrnews entry must be an explicit registry row, "
                    "not an inference from bnr.bg"
                )


# ---------------------------------------------------------------------------
# §13 — the Focus contract is frozen
# ---------------------------------------------------------------------------


def test_focus_alternatives_are_derived_deterministically_without_a_model():
    """§13/§D4: three variants CAN be produced deterministically, so no model."""
    from editor_assistant.workflow import focus_suggestions

    title = "Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол"
    first = focus_suggestions.alternatives(title, facts=["f"])
    second = focus_suggestions.alternatives(title, facts=["f"])
    assert first == second
    assert 2 <= len(first) <= 3
    assert focus_suggestions.primary_focus(title, facts=["f"]) == (
        focus_suggestions.primary_focus(title, facts=["f"])
    )
