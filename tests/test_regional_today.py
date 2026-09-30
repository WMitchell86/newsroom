"""V1.2-G4.1 §A — `Днес` is a Burgas-region working desk, deterministically.

The owner's manual test after G3/G4 showed a national-news list where a regional
desk should have been: Северна Македония / ЕК integration, Ирак consultations,
national youth football and an АЕЖ workshop all sat on the same screen as real
Burgas Stories. Tracing the real corpus showed there was **no locality decision in
the Today path at all** — `project_today` admitted any Story that was new inside
the horizon, and `bta-burgas` is a `kind: media` row on the *national* domain
`bta.bg` whose monitoring query returns the whole wire.

These tests pin the replacement rule and, just as importantly, pin what it must
NOT do: no relevance score, no ranking, no model call, and no deletion. Every
fixture is real Burgas or real national material taken from the corpus that
produced the owner's screenshot.

Nothing here writes to the repository's real runtime stores: every fixture is
built under `tmp_path` through the canonical stores.
"""

from __future__ import annotations

import json

import pytest

from editor_assistant.workflow import (
    editor_queries,
    inbox_store,
    regional_scope,
    story_store,
)

NOW = "2026-09-27T09:00:00Z"

#: The registry kinds that decide locality, exactly as G4 stores them. Written
#: through the real registry so the rows are valid canonical entries, not a
#: hand-written approximation: an entry the registry would refuse could never
#: exist in a real newsroom, so a test that used one would be testing fiction.
_REGISTRY_BASE = {
    "collector": "google_news_rss",
    "query": "",
    "url": "",
    "status": "active",
    "muted_until": "",
    "priority": "normal",
    "cadence": "each_run",
    "factual_authority": False,
    "calendar": False,
    "note": "",
}


def _registry_row(source_id: str, name: str, kind: str, domain: str) -> dict:
    return {
        **_REGISTRY_BASE,
        "source_id": source_id,
        "name": name,
        "kind": kind,
        "domain": domain,
        # The registry requires a query for this collector, exactly as it would
        # in a real newsroom; `validate_entry` enforces it and these rows are read
        # back through `read_registry`, not hand-fed to the predicate.
        "query": name,
        "added_at": "2026-09-21T17:00:00Z",
        "updated_at": "2026-09-21T17:00:00Z",
    }


REGISTRY = [
    # Local institutions and local outlets: the regional stack.
    _registry_row("burgas-municipality", "Община Бургас", "official", "burgas.bg"),
    _registry_row("pomorie-municipality", "Община Поморие", "official", "pomorie.bg"),
    _registry_row("odmvr-burgas", "ОДМВР Бургас", "official", "mvr.bg"),
    _registry_row("chernomorski-far", "Черноморски фар", "regional", "faragency.bg"),
    # National publishers and the catch-all monitoring query: authority, never locality.
    _registry_row("bta-burgas", "БТА — област Бургас", "media", "bta.bg"),
    _registry_row("bnr-burgas", "БНР Бургас", "media", "bnr.bg"),
    _registry_row("google-news-burgas-region", "Бургаски регион (наблюдение)", "aggregator", ""),
]


def _item(item_id: str, *, title: str, source_id: str, summary: str = "") -> dict:
    return {
        "item_id": item_id,
        "source_id": source_id,
        "source_item_id": item_id,
        "title": title,
        "url": f"https://publisher.example/{item_id}",
        "published_at": NOW,
        "discovered_at": NOW,
        "summary": summary or f"Обобщение: {title}",
        "source_kind": "media",
        "publisher_domain": "publisher.example",
        "status": "NEW",
        "priority": "normal",
        "event_at": "",
        "event_end_at": "",
        "factual_authority": False,
        "publisher_kind": "",
    }


def _story(story_id: str, item_id: str, *, now: str = NOW) -> dict:
    story = story_store.new_story(_item(item_id, title="Материал", source_id="s"), now=now)
    story["story_id"] = story_id
    story["status"] = "NEW"
    story["representative_item_id"] = item_id
    story["members"] = [
        {
            "item_id": item_id,
            "publication_key": f"p-{item_id}",
            "relation": "ORIGIN",
            "relation_source": "first_item",
            "added_at": now,
        }
    ]
    return story


@pytest.fixture
def newsroom(tmp_path, monkeypatch):
    """An isolated newsroom whose registry mirrors the real regional stack.

    `WB_EDITORIAL_WORKFLOW_DIR` is redirected as well: `read_today` reads the
    Article store by default, and without this the real repository's Articles
    would be joined against this fixture's Stories — exactly the cross-store leak
    the harness forbids.
    """
    root = tmp_path / "newsroom"
    root.mkdir()
    monkeypatch.setenv("WB_NEWSROOM_DIR", str(root))
    monkeypatch.setenv("NEWSROOM_DIR", str(root))
    monkeypatch.setenv("WB_EDITORIAL_WORKFLOW_DIR", str(tmp_path / "editorial"))
    (root / "sources.json").write_text(json.dumps(REGISTRY, ensure_ascii=False), encoding="utf-8")

    return root


def _desk(
    newsroom,
    stories,
    items,
    *,
    scope=editor_queries.SCOPE_REGION,
    article_root=None,
    article_next_actions=None,
):
    inbox = newsroom / "inbox.jsonl"
    inbox_store.save_items(items, inbox)
    story_store.write_store({"stories": stories, "overrides": {}}, newsroom / "stories.json")
    return editor_queries.read_today(
        stories_path=newsroom / "stories.json",
        inbox_path=inbox,
        metadata_root=newsroom,
        article_root=article_root,
        article_next_actions=article_next_actions,
        now=NOW,
        scope=scope,
    )


# --------------------------------------------------------------------------
# §A3 — a national publisher is not local; a national ITEM is not regional
# --------------------------------------------------------------------------


def test_a_national_wire_story_is_excluded_from_the_regional_desk(newsroom):
    """The owner's screen: Ирак/ЕК/Северна Македония must leave the desk.

    These are the exact national items the owner reported, each discovered by the
    `bta-burgas` source whose registry NAME mentions Burgas. The name must not be
    mistaken for a locality signal — only the Story's own text is read.
    """
    national = [
        ("s-iraq", "i-iraq", "ИНА: Ирак и България подписаха меморандум за разбирателство за сътрудничество", "bta-burgas"),
        ("s-eu", "i-eu", "ЕК представи данни за движението на пет наказателни процедури срещу България", "bta-burgas"),
        ("s-mk", "i-mk", "Кристиан Вигенин за БТА: България и Северна Македония нямат нужда от посредник", "bta-burgas"),
        ("s-football", "i-football", "България победи Португалия в квалификациите за Евро 2027 при младежите", "bta-burgas"),
        ("s-aej", "i-aej", "АЕЖ-България организира онлайн работилница за журналистическо отразяване на климата", "bta-burgas"),
    ]
    stories = [_story(sid, iid) for sid, iid, _title, _src in national]
    items = [_item(iid, title=title, source_id=src, summary="") for _sid, iid, title, src in national]
    result = _desk(newsroom, stories, items)

    assert result["stories"] == [], "national wire copy must not occupy the Burgas desk"
    assert result["storyAttentionTotal"] == 0
    # §A4: nothing is deleted. The same Stories are all still present in the
    # unfiltered scope and reachable under «Истории».
    everything = _desk(newsroom, stories, items, scope=editor_queries.SCOPE_ALL)
    assert len(everything["stories"]) == len(national)
    assert len(story_store.read_store(newsroom / "stories.json")["stories"]) == len(national)


def test_a_national_publisher_writing_about_burgas_is_kept(newsroom):
    """§A3 both ways: locality comes from the TEXT, not from the publisher.

    `bta-burgas` is a national `kind: media` row. A BTA item about the Burgas
    municipality is regional on the strength of its own headline, and must stay
    on the desk — otherwise the rule would throw away exactly the BTA municipal
    coverage a local newsroom wants.
    """
    stories = [_story("s-bta-burgas", "i-bta-burgas")]
    items = [
        _item(
            "i-bta-burgas",
            title="Община Бургас обяви нови дати за записане в детските градини",
            source_id="bta-burgas",
            summary="",
        )
    ]
    result = _desk(newsroom, stories, items)

    assert [row["title"] for row in result["stories"]] == [
        "Община Бургас обяви нови дати за записане в детските градини"
    ]


@pytest.mark.parametrize(
    "title",
    [
        "Катастрофа затвори пътя Несебър - Бургас",
        "490 катастрофи с 23-ма загинали са станали в Бургаско през 2025 г.",
        "Общинският съвет в Царево връчи звания Почетен гражданин",
        "Поморие с нова чешма до края на месеца",
        "Созопол приема фестивала на виното през август",
        "Приморско и Несебър с общ транспортен билет",
        "Карнобат започна ремонт на централния площад",
        "Айтос и Лозенец с обща транспортна линия",
        "Руен избра нова площадка за паркинг",
        "Каблешково домакинства празника на града",
        "Черноморец промени маршрута на автобуса",
        "Ахтопол отвори сезона на фестивала",
    ],
)
def test_the_closed_locality_vocabulary_is_recognised(newsroom, title):
    """§A2: the listed localities qualify, in their plain and adjectival forms."""
    stories = [_story("s-locality", "i-locality")]
    items = [_item("i-locality", title=title, source_id="bta-burgas", summary="")]
    result = _desk(newsroom, stories, items)
    assert len(result["stories"]) == 1, title


def test_a_national_coast_word_is_not_a_burgas_locality():
    """`Черноморието` is this site's own name; `черноморски` is the whole coast.

    §A2's `черноморец` is deliberately the town, not a `черномор` stem. A stem
    would pull Varna and Varna-oblat news onto a Burgas desk, which is the same
    class of mistake as reading the source's name.
    """
    assert regional_scope.mentions_region("Черноморец обяви нова програма") is True
    assert regional_scope.mentions_region("Варна приема BLACK SEA OPEN") is False
    assert regional_scope.mentions_region("черноморските курорти са пълни") is False
    assert regional_scope.mentions_region("chernomorie-bg.com публикува") is False


# --------------------------------------------------------------------------
# §A2 rule 1 — a configured local source qualifies on its own
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source_id",
    # V1.2-G4.26: `chernomorski-far` was in this list and is removed. It is
    # `kind="regional"` on `faragency.bg` — a NATIONAL directorate of lighthouses,
    # not a Burgas institution — and the row is a regional outlet, so under the
    # sharpened rule it no longer qualifies without regional text. The three
    # that remain are genuine self-scoping institutions: two municipalities and
    # the district police. The original rationale still holds for all of them; it
    # never held for a national agency wearing a local name.
    ["burgas-municipality", "pomorie-municipality", "odmvr-burgas"],
)
def test_a_local_source_qualifies_its_story_without_a_locality_in_the_text(newsroom, source_id):
    """Rule 1: the registry, not the headline.

    A municipal or police notice legitimately has no place name in its headline
    ("Декемврийските награди са обявени"), and it is still regional because the
    editor configured that source as a local institution.
    """
    stories = [_story("s-local-source", "i-local-source")]
    items = [
        _item("i-local-source", title="Декемврийските награди са обявени", source_id=source_id)
    ]
    result = _desk(newsroom, stories, items)
    assert len(result["stories"]) == 1


def test_a_national_or_aggregator_source_is_never_local_by_configuration(newsroom):
    """§A3: authority and locality are separate concepts.

    `bnr-burgas` and the catch-all `google-news-burgas-region` monitoring query
    are configured sources, and neither may make a Story regional on its own.
    """
    for source_id in ("bnr-burgas", "google-news-burgas-region"):
        assert regional_scope.is_local_source(source_id, REGISTRY) is False
    stories = [_story("s-nat", "i-nat")]
    items = [_item("i-nat", title="Декемврийските награди са обявени", source_id="bnr-burgas")]
    assert _desk(newsroom, stories, items)["stories"] == []

def test_an_unconfigured_source_is_not_local():
    """No registry row means no local claim was ever made.

    Defaulting an unknown source to local would reopen the national-wire hole the
    rule exists to close, so absence is answered honestly as "not local".
    """
    assert regional_scope.is_local_source("never-configured", REGISTRY) is False
    assert regional_scope.is_local_source("", REGISTRY) is False


# --------------------------------------------------------------------------
# §A2 rule 3 — the editor never loses in-flight work
# --------------------------------------------------------------------------


def test_a_story_with_an_active_article_is_always_kept(newsroom):
    """Rule 3a: a Story the editor is already writing is never filtered out.

    Deliberately a national headline on a national source: locality is
    undetermined, and hiding it would hide the editor's own work.
    """
    from editor_assistant.workflow import editor_article_store

    stories = [_story("s-active", "i-active")]
    items = [
        _item(
            "i-active",
            title="Кристиан Вигенин за БТА: България и Северна Македония нямат нужда от посредник",
            source_id="bta-burgas",
        )
    ]
    article_root = newsroom / "editorial"
    _desk(newsroom, stories, items, article_root=article_root)
    article = editor_article_store.create_editor_article(
        story_id="s-active",
        stories_path=newsroom / "stories.json",
        working_title="Работа по темата",
        now=NOW,
        root=article_root,
    )
    editor_article_store.update_editor_focus(
        article["article_id"], "Да обясним позицията.", root=article_root
    )

    result = _desk(
        newsroom,
        stories,
        items,
        article_root=article_root,
        article_next_actions={article["article_id"]: "SELECT_FOCUS"},
    )
    assert [row["id"] for row in result["stories"]] == ["s-active"]
    # The same Article is also surfaced as work, not only as a Story row.
    assert [entry["article"]["id"] for entry in result["articles"]] == [article["article_id"]]


def test_a_followed_story_with_an_unreviewed_development_is_kept(newsroom):
    """Rule 3b: following a Story is the editor's own instruction to keep it."""
    from editor_assistant.workflow import story_editor_metadata

    stories = [_story("s-followed", "i-followed")]
    # A second member classified as a new development: following alone is not
    # enough, the editor must have something unseen, exactly as the editorial
    # projections define it.
    stories[0]["members"].append(
        {
            "item_id": "i-followed-2",
            "publication_key": "p-i-followed-2",
            "relation": "NEW_DEVELOPMENT",
            "relation_source": "manual",
            "added_at": NOW,
        }
    )
    items = [
        _item(
            "i-followed",
            title="Кредитирането в България е запазило двуцифрения си ръст през август",
            source_id="bnr-burgas",
        ),
        _item(
            "i-followed-2",
            title="Нови данни за същия пазар",
            source_id="bnr-burgas",
        ),
    ]
    _desk(newsroom, stories, items)
    story_editor_metadata.set_story_followed(
        "s-followed", True, stories_path=newsroom / "stories.json", root=newsroom
    )

    result = _desk(newsroom, stories, items)
    assert [row["id"] for row in result["stories"]] == ["s-followed"]


def test_a_followed_story_without_a_new_development_is_still_filtered(newsroom):
    """Following is not a blank cheque: rule 3b requires an unseen development.

    Without this, every followed Story would sit on the regional desk forever,
    which is the same "never retires" defect the horizon rule was written to
    avoid.
    """
    from editor_assistant.workflow import story_editor_metadata

    stories = [_story("s-followed-quiet", "i-followed-quiet")]
    items = [
        _item(
            "i-followed-quiet",
            title="Кредитирането в България е запазило двуцифрения си ръст през август",
            source_id="bnr-burgas",
        )
    ]
    _desk(newsroom, stories, items)
    story_editor_metadata.set_story_followed(
        "s-followed-quiet", True, stories_path=newsroom / "stories.json", root=newsroom
    )

    assert _desk(newsroom, stories, items)["stories"] == []


# --------------------------------------------------------------------------
# §A4 / §A5 — the scope toggle, and the absence of any score
# --------------------------------------------------------------------------


def test_the_default_scope_is_the_region_and_all_is_the_escape_hatch(newsroom):
    stories = [_story("s-local", "i-local"), _story("s-national", "i-national")]
    items = [
        _item("i-local", title="Катастрофа затвори пътя Несебър - Бургас", source_id="bta-burgas"),
        _item(
            "i-national",
            title="България притежава всичко, за да бъде домакин и на световно първенство",
            source_id="bta-burgas",
        ),
    ]
    regional = _desk(newsroom, stories, items)
    everything = _desk(newsroom, stories, items, scope=editor_queries.SCOPE_ALL)

    assert regional["scope"] == editor_queries.SCOPE_REGION
    assert [row["id"] for row in regional["stories"]] == ["s-local"]
    assert everything["scope"] == editor_queries.SCOPE_ALL
    assert [row["id"] for row in everything["stories"]] == ["s-local", "s-national"]


def test_an_unknown_scope_falls_back_to_the_regional_default(newsroom):
    """A bad value must not silently widen the desk to every Story."""
    stories = [_story("s-local", "i-local"), _story("s-national", "i-national")]
    items = [
        _item("i-local", title="Община Царево обяви нови правила", source_id="bta-burgas"),
        _item(
            "i-national",
            title="Юношите на България и Естония завършиха наравно",
            source_id="bta-burgas",
        ),
    ]
    result = _desk(newsroom, stories, items, scope="nonsense")
    assert result["scope"] == editor_queries.SCOPE_REGION
    assert [row["id"] for row in result["stories"]] == ["s-local"]


def test_the_regional_rule_is_a_plain_predicate_with_no_numeric_ranking(newsroom):
    """§A5: one understandable yes/no rule, not a relevance ranking.

    The module exposes no numeric relevance, no weighting and no ordering
    function, and the decision for a Story is a plain boolean — so the editor can
    always be told *why* a Story is on the desk. Only the prose is scanned: the
    module's own comments legitimately discuss what it deliberately does NOT do.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(regional_scope))
    functions = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    # No ranking/ordering entry point exists at all.
    assert not [
        name
        for name in functions
        if any(token in name for token in ("rank", "relevance", "score", "weight", "priorit"))
    ]
    decision = regional_scope.story_is_regional(
        _story("s", "i"),
        {},
        {"i": _item("i", title="Нищо общо", source_id="bta-burgas")},
        title="Нищо общо",
        registry_rows=REGISTRY,
    )
    # A real yes/no, not a graded value.
    assert decision is False


def test_the_dto_echoes_the_scope_it_was_built_with(newsroom):
    """§A4: the wire says which desk it is, so nothing has to guess from rows.

    The projection echoes the decision the projection actually made. A DTO that
    omitted it would leave the editor unable to tell a regional desk from an
    unfiltered one except by counting rows, which is not a contract.
    """
    from editor_assistant.workflow import editor_application as app

    stories = [_story("s-local", "i-local"), _story("s-national", "i-national")]
    items = [
        _item("i-local", title="Община Царево обяви нови правила", source_id="bta-burgas"),
        _item(
            "i-national",
            title="Юношите на България и Естония завършиха наравно",
            source_id="bta-burgas",
        ),
    ]
    _desk(newsroom, stories, items)

    assert app.read_today(scope="region")["scope"] == editor_queries.SCOPE_REGION
    assert app.read_today(scope="all")["scope"] == editor_queries.SCOPE_ALL
    # And an unrecognised scope is answered honestly, not silently widened.
    assert app.read_today(scope="nonsense")["scope"] == editor_queries.SCOPE_REGION
