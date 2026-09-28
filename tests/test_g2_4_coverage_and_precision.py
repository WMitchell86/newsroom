"""V1.2-G2.4 — extraction precision (§A), event coverage (§B), Focus (§D),
the official-source authority trace (§R1/§R2) and the single-source experiment (§E).

Every test here is a PERMANENT regression for a defect that actually occurred in
the frozen 24-Story replay or in the owner's own screenshot, not a hypothetical.
"""


from __future__ import annotations

import pytest

from editor_assistant.sources import html_desc
from editor_assistant.workflow import claim_quality as cq
from editor_assistant.workflow import (
    draft_material,
    event_search,
    focus_suggestions,
    newsroom_run,
    single_source_policy,
    story_research,
    story_store,
)

# ---------------------------------------------------------------------------
# §A2 — the structural cause of the heading-plus-sentence merges
# ---------------------------------------------------------------------------

#: The real G2.3 defect: a heading concatenated with the paragraph under it.
G23_HEADING_MERGE = "Мъжки сингъл – любители Към момента за турнира са заявени 12 отбора."


def test_typed_blocks_separate_a_heading_from_its_sentence():
    """§A2: the heading and the sentence are DIFFERENT blocks, not one run.

    Proven at the segmentation layer rather than by blacklisting the observed
    string — the three observed strings are named nowhere in the implementation.
    """
    html = (
        "<article><h2>Мъжки сингъл – любители</h2>"
        "<p>Към момента за турнира са заявени 12 отбора.</p></article>"
    )
    assert [b["kind"] for b in html_desc.normalize_blocks(html)] == [
        html_desc.HEADING,
        html_desc.PROSE,
    ]


def test_a_heading_never_becomes_part_of_a_fact():
    """§A2: with typed blocks, the merged sentence cannot be produced at all."""
    blocks = html_desc.normalize_blocks(
        "<article><h2>Мъжки сингъл – любители</h2>"
        "<p>Към момента за турнира са заявени 12 отбора.</p></article>"
    )
    texts = [c["text"] for c in cq.select_candidate_claims(None, [], blocks=blocks)]
    assert G23_HEADING_MERGE not in texts
    assert not any("Мъжки сингъл" in text for text in texts)


def test_a_navigation_run_is_never_classified_as_prose():
    blocks = html_desc.normalize_blocks(
        "<nav><a>Начало</a><a>Новини</a></nav><p>Събитието започна в 18 часа днес.</p>"
    )
    kinds = [b["kind"] for b in blocks]
    assert html_desc.NAV in kinds and html_desc.PROSE in kinds


def test_plain_text_pages_still_work_as_one_prose_block():
    """A page with no markup must behave exactly as before the repair."""
    blocks = html_desc.normalize_blocks("Събитието започна в 18 часа на 25 септември.")
    assert [b["kind"] for b in blocks] == [html_desc.PROSE]


@pytest.mark.parametrize(
    "html",
    [
        # A container the page never closes. Real markup omits end tags, and the
        # failure is SILENT: every later paragraph is labelled NAV and lost, which
        # looks exactly like "this page had no usable text".
        "<nav><a>Меню</a><p>Реален факт за Бургас днес.</p>",
        "<header><h1>Заглавие</h1><p>Реален факт за Бургас днес.</p>",
        "<aside>Сподели</aside><p>Реален факт за Бургас днес.</p>",
        # Crossing / mismatched end tags.
        "<nav><div></span></nav><p>Реален факт за Бургас днес.</p>",
    ],
)
def test_an_unclosed_container_never_swallows_the_article(html):
    """§A2 recovery: broken markup must not delete real prose."""
    blocks = html_desc.normalize_blocks(html)
    assert any(b["kind"] == html_desc.PROSE and "Реален факт" in b["text"] for b in blocks), blocks


def test_well_formed_navigation_is_still_navigation():
    """The recovery must not demote a real menu to prose."""
    html = "<nav>" + "<a>Начало</a><a>Новини</a><a>Култура</a>" * 10 + "</nav><p>Реален факт.</p>"
    blocks = html_desc.normalize_blocks(html)
    assert blocks[0]["kind"] == html_desc.NAV
    assert any(b["kind"] == html_desc.PROSE and "Реален факт" in b["text"] for b in blocks)


@pytest.mark.parametrize(
    "text",
    [
        # Legal and administrative references glue a digit to a capital constantly.
        # An earlier version of the artefact rule rejected every one of these, and
        # council stories are a large share of this corpus.
        "Решение 12А на ОбС е прието на заседанието в сградата на Община Бургас.",
        "Отдел 3Б ще извърши проверката на обектите през месец октомври 2026 г.",
    ],
)
def test_an_article_reference_is_not_a_renderer_artefact(text):
    """§A2: the glued-node rule must demand a RUN, not a single citation."""
    assert cq.is_factual_candidate(text) is True


# ---------------------------------------------------------------------------
# §A3 — the generalised tag-cloud / widget classes
# ---------------------------------------------------------------------------

G23_TAG_CLOUD = (
    "#катастрофа На мястото на инцидента станаха часът и мястото на инцидента "
    "БНР изпрати свой репортаж Новини Нашите инициативи БНР"
)


@pytest.mark.parametrize(
    "text",
    [
        G23_TAG_CLOUD,                                       # the observed blob
        "Сподели статията във Фейсбук и ни последвай",               # share/follow
        "Препоръчано за вас: Още от автора на статията",          # recommendation
        "Свързани статии: още три материала по темата",
        "#бургас",                                        # one hashtag is a tag
    ],
)
def test_tag_cloud_and_widget_classes_are_chrome(text):
    assert cq.is_chrome(text) is True
    assert cq.is_factual_candidate(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата.",
        "Две деца пострадаха при катастрофата на пътя.",
        "Радослав Бимбалов ще представи новия си роман в бургаската библиотека.",
        "На 30 септември от 18 часа ще бъде представен романът в библиотеката.",
    ],
)
def test_legitimate_short_sentences_are_not_over_filtered(text):
    """§A3 explicitly forbids over-filtering: the classes must stay narrow."""
    assert cq.is_chrome(text) is False


#: Real promoted facts from the G2.4 replay that were NOT facts. Every one is a
#: renderer artefact, and each is a property of the TEXT rather than of a
#: publisher: an accessibility skip link, and a whitespace-less node boundary.
G24_RENDERER_ARTEFACTS = (
    (
        "сеп.212026ПресцентърСпортНа 19 и 20 септември се състоя първият кръг от "
        "първенството на детския отбор на ОФК „Поморие“."
    ),
    (
        "Резултати от срещите на детско-юношеските школи на ОФК „Поморие“ за 19 и 20 "
        "септември – Община Поморие Skip to content 27.09.2026г."
    ),
    (
        "2 публикацииНа 21 септември се отбелязва Световният ден за информираност "
        "за болестта на Алцхаймер."
    ),
    (
        "сеп.142026ПресцентърСпортНа 12 и 13 септември 2026 година започнаха "
        "първенствата на детско-юношеската школа на Общински футболен клуб „Поморие“."
    ),
)


@pytest.mark.parametrize("text", G24_RENDERER_ARTEFACTS)
def test_renderer_artefacts_are_chrome(text):
    """§A2 second pass: a glued node run and a skip link are never facts."""
    assert cq.is_chrome(text) is True
    assert cq.is_factual_candidate(text) is False


#: Real promoted facts from the G2.4 replay that were TRUNCATED PREVIEWS. A
#: teaser ends in an ellipsis because the publisher cut it, so it states no
#: complete proposition.
G24_TRUNCATED_PREVIEWS = (
    "Община Поморие започва подготовката за 2027 г., когато Бургас ще…",
    "Центърът за подкрепа за личностно развитие Общински детски комплекс –…",
    "Днес, на 22 септември, отбелязваме 118 години от обявяването на…",
    "На 19 и 20 септември се състоя първият кръг от…",
)


@pytest.mark.parametrize("text", G24_TRUNCATED_PREVIEWS)
def test_a_truncated_preview_is_never_a_fact(text):
    """§A2 third pass: a cut-off teaser is chrome however well-formed it looks."""
    assert cq.is_factual_candidate(text) is False


def test_a_leading_preposition_does_not_cost_a_real_fact():
    """The rule this slice deliberately did NOT add, and why.

    Rejecting a leading preposition would catch the marginal fragment
    "от 9:00 часа, в заседателната зала…", but it also rejects two complete
    Bulgarian sentences that were promoted in the replay. That trade was
    measured and rejected; the residual fragment is reported as QUESTIONABLE.
    """
    assert cq.is_factual_candidate(
        "На 21 септември се отбелязва Световният ден за информираност."
    )
    assert cq.is_factual_candidate("В Бургас денят беше отбелязан със специален флашмоб.")


@pytest.mark.parametrize(
    "text",
    [
        (
            "На 21 септември се отбелязва Световният ден за информираност за "
            "болестта на Алцхаймер."
        ),
        (
            "Четирите гола за Поморие бяха дело на Калоян Димов – 2 гола, Пламен "
            "Продромов – 1 гол и Александър Демирев – 1 гол."
        ),
        "Те срещнаха отбора на ФК „Карнобат“ и загубиха с 1 – 6.",
        "Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол вчера.",
        (
            "В центъра на романа е балкански град, чиито жители решават да "
            "построят физическа стена."
        ),
    ],
)
def test_real_facts_survive_the_renderer_filter(text):
    """The filter must catch artefacts without eating genuine sentences."""
    assert cq.is_factual_candidate(text) is True


# ---------------------------------------------------------------------------
# §A4 — event anchors, and the real wrong-event attribution
# ---------------------------------------------------------------------------

BURGAS_SOZOPOL = "Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол"
#: The real G2.3 wrong-event attribution, verbatim.
STARA_ZAGORA_CLAIM = "При катастрофа на пътя Стара Загора – Казанлък пострадаха двама души."


def test_generic_news_words_never_become_anchors():
    """§A4: `катастрофа` identifies no event, so it can never create agreement."""
    anchors = cq.event_anchors(BURGAS_SOZOPOL)
    assert not any("катастроф" in key for key in anchors)


def test_a_different_accident_is_rejected_without_a_model():
    """§A4: the Stara Zagora–Kazanlak claim cannot enter the Burgas–Sozopol Story."""
    anchors = cq.event_anchors(BURGAS_SOZOPOL)
    assert cq.agrees_with_event(STARA_ZAGORA_CLAIM, anchors, topic=BURGAS_SOZOPOL) is False


def test_the_same_event_from_another_publisher_is_kept():
    anchors = cq.event_anchors(BURGAS_SOZOPOL)
    same = "Жена и 3-годишно дете пострадаха при катастрофа на пътя Бургас-Созопол."
    assert cq.agrees_with_event(same, anchors, topic=BURGAS_SOZOPOL) is True


def test_a_shared_generic_word_alone_is_never_enough():
    """§A4: it is the WORD that is disallowed, not the count.

    `пострадаха` and `катастрофа` are removed from every anchor set, so a claim
    that shares only generic news vocabulary agrees with nothing and is refused.
    """
    topic = "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата"
    anchors = cq.event_anchors(topic)
    unrelated = "Днес е хубаво време за разходка извън града."
    assert cq.agrees_with_event(unrelated, anchors, topic=topic) is False


def test_a_real_fact_of_the_same_event_is_not_over_filtered():
    """The recall side of §A4: a real detail of THIS event must survive.

    Measured on the live BNR accident page, this sentence shares only `жена`
    with its own Story. Requiring two anchors rejected it for no safety gain.
    """
    # The real Story title from the frozen sample, and the real sentence from
    # the live BNR page about it. The sentence names no locality and no date; it
    # is recognisably the same event purely from `жена`.
    real_topic = "Жена и 3-годишно дете пострадаха при катастрофа на пътя Бургас-Созопол"
    anchors = cq.event_anchors(real_topic)
    detail = "Ранени при инцидента са 30-годишна жена и момиченце на 3 години."
    assert cq._content_keys(detail) & anchors          # the link that must hold
    assert cq.agrees_with_event(detail, anchors, topic=real_topic) is True


def test_a_story_with_no_usable_anchors_is_not_filtered():
    """A subject too thin to identify an event must not reject everything."""
    assert cq.agrees_with_event("Някакво изречение.", cq.event_anchors("Тест")) is True


#: Facts promoted by the G2.4B replay that were NOT facts. The higher recall
#: exposed three classes the tighter G2.4 gate had masked: a sentence boundary
#: whose space the source omitted, a related-article widget, and a digit glued
#: to a unit word.
G24B_RENDERER_ARTEFACTS = (
    # A related-article widget naming ANOTHER story on the same publisher. This
    # is the worst of the three: it carried a genuinely different event
    # ("Достойни личности ... наградени") into a football Story.
    "ПредишнаPrevious post:Достойни личности от Поморие бяха наградени за принос в културата.",
    "Продължение: Предишна статия разглежда друг въпрос изцяло.",
    # A digit glued to a unit word; Bulgarian always writes a space.
    "Футбол 9се срещнаха с отбора на ФК „Бургас спорт“.",
    # A subscription / channel call-to-action: a site promotion, not a
    # statement about the event.
    (
        "За още новини и предстоящи събития се присъединете към Община Поморие – "
        "актуални новини във Viber."
    ),
    "Абонирайте се за бюлетина на сайта, за да получавате всички новини първи.",
)


@pytest.mark.parametrize("text", G24B_RENDERER_ARTEFACTS)
def test_a_related_article_widget_is_never_a_fact(text):
    """§A2: a pager widget names another story, so it is never this event."""
    assert cq.is_factual_candidate(text) is False


def test_a_sentence_boundary_without_a_space_is_still_a_boundary():
    """§A2: the source omitted the space; the split must not depend on it."""
    merged = (
        "Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол вчера, "
        "съобщават от полицията.Колата, в която пътували е била ударена."
    )
    parts = cq.SENTENCE_SPLIT.split(merged)
    assert len(parts) == 2, parts
    assert parts[0].endswith("полицията.")
    assert parts[1].startswith("Колата")


def test_related_article_widgets_never_reach_the_candidate_pool():
    """End to end: a widget and the other story it links to are both refused."""
    from editor_assistant.sources import html_desc as _html

    html = (
        "<article><p>Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол "
        "вчера, съобщават от полицията.<b>Колата</b>, в която пътували е била ударена.</p>"
        "<p>Предишна<a>Previous post</a>:Достойни личности от Поморие бяха наградени "
        "за принос в културата в рамките на фестивала.</p>"
        "<p>Жената е с контузия на корема, а детето с травма на главата.</p></article>"
    )
    topic = "Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол"
    texts = [c["text"] for c in cq.select_candidate_claims(
        None, [], blocks=_html.normalize_blocks(html), topic=topic
    )]
    assert texts, "the real claims must survive"
    assert not any("Предишна" in t or "наградени" in t for t in texts)
    assert not any("полицията.Колата" in t for t in texts)


# ---------------------------------------------------------------------------
# §B1/§B2 — the deterministic query ladder
# ---------------------------------------------------------------------------


def test_the_road_query_carries_the_event_action():
    """§B1 — a road pair ALONE is too generic; measured, it returns bus routes.

    `"Бургас-Созопол"` alone brings back timetables; the same pair plus the
    event's own action words brings back the publishers that covered the
    accident. The full subject stays the most specific query.
    """
    queries = event_search.event_queries(event_search.event_anchors(BURGAS_SOZOPOL))
    assert queries[0] == f'"{BURGAS_SOZOPOL}"'
    assert queries[1] == '"Бургас-Созопол" пострадаха катастрофа'


def test_the_ladder_is_bounded_and_never_repeats():
    queries = event_search.event_queries(event_search.event_anchors(BURGAS_SOZOPOL))
    assert len(queries) <= event_search.MAX_TOTAL_QUERIES
    assert len(set(queries)) == len(queries)


def test_a_stronger_locality_suppresses_the_generic_region():
    """§B1: `Бургас` is never appended blindly to a Story with its own place."""
    queries = event_search.event_queries(event_search.event_anchors(BURGAS_SOZOPOL))
    assert not any(q.endswith(event_search.DEFAULT_LOCATION) for q in queries)


def test_the_generic_region_is_a_last_resort_never_a_default():
    """§B1: the region is appended only when the Story offers nothing better.

    A Story with distinctive terms gets a Tier-3 query built from THEM, not from
    the region; only a Story with neither entity nor distinctive term falls back.
    """
    with_terms = event_search.event_queries(
        event_search.event_anchors("Нов спортен комплекс отвори врати")
    )
    assert any("комплекс" in q for q in with_terms)
    assert not any(q.endswith(event_search.DEFAULT_LOCATION) for q in with_terms)
    bare = event_search.event_queries(event_search.event_anchors(""))
    assert bare == []


def test_the_ladder_is_deterministic():
    anchors = event_search.event_anchors(BURGAS_SOZOPOL)
    assert event_search.event_queries(anchors) == event_search.event_queries(anchors)


def test_the_serper_budget_is_policy_and_cannot_be_raised():
    """§B5: a caller may spend LESS, never more, of the owner's allocation."""
    from editor_assistant.workflow import search as search_mod

    spent = {"n": 0}

    class _Provider:
        name = "serper"

        def search(self, query, **kw):
            spent["n"] += 1
            return {"status": search_mod.SEARCH_OK, "results": []}

    op = search_mod.run_event_discovery(
        topic=BURGAS_SOZOPOL,
        constraints=search_mod.make_constraints(description="x", location="Бургас"),
        provider=_Provider(),
        page_opener=lambda _url: (_ for _ in ()).throw(RuntimeError("no network")),
        serper_budget=99,          # a caller asking for far more
        env={},                    # no Serper key -> the stub chain only
    )
    # With no Serper key the chain contributes nothing, so the clamp is asserted
    # structurally as well: the recorded budget can never exceed the policy.
    assert op["serper_budget"] <= event_search.MAX_SERPER_QUERIES_PER_ROUND


# ---------------------------------------------------------------------------
# §B7 — the deterministic result filter
# ---------------------------------------------------------------------------

#: The exact §B7 pair from the brief.
SAME_EVENT_RESULT = {
    "title": "Майка и дете пострадаха при катастрофа на пътя Бургас-Созопол",
    "url": "https://bnr.bg/bg/a/1",
    "snippet": "инцидент на пътя",
}
OTHER_EVENT_RESULT = {
    "title": "Катастрофа край Казанлък: удариха кола, загина човек",
    "url": "https://flagman.bg/a/2",
    "snippet": "Казанлък инцидент",
}


def test_the_same_event_result_is_ranked_first():
    anchors = event_search.event_anchors(BURGAS_SOZOPOL)
    kept = event_search.event_filter(anchors, [OTHER_EVENT_RESULT, SAME_EVENT_RESULT])
    assert kept[0]["url"] == SAME_EVENT_RESULT["url"]


def test_a_contradictory_locality_is_dropped_before_opening():
    """§B7: the Kazanlak page is rejected from metadata, before the open."""
    anchors = event_search.event_anchors(BURGAS_SOZOPOL)
    kept = event_search.event_filter(anchors, [OTHER_EVENT_RESULT])
    assert all(row["url"] != OTHER_EVENT_RESULT["url"] for row in kept)



# ---------------------------------------------------------------------------
# §R1/§R2 — the official-source authority trace
# ---------------------------------------------------------------------------


def test_publisher_identity_collapses_a_www_prefix():
    """§R1: `www.burgas.bg` IS the registry's `burgas.bg` publisher."""
    assert story_store.publisher_identity("www.burgas.bg") == "burgas.bg"
    assert story_store.publisher_identity("m.dariknews.bg") == "dariknews.bg"
    assert story_store.publisher_identity("") == ""


def test_the_publisher_count_uses_publisher_identity_not_the_raw_domain():
    """§F: a subdomain must not manufacture a second publisher."""
    story = {"members": [{"item_id": "a", "publication_key": "p1"},
                         {"item_id": "b", "publication_key": "p2"}]}
    items = {"a": {"publisher_domain": "www.burgas.bg"},
             "b": {"publisher_domain": "burgas.bg"}}
    assert story_store.metrics(story, items)["publisher_count"] == 1


def test_two_real_publishers_still_count_as_two():
    story = {"members": [{"item_id": "a", "publication_key": "p1"},
                         {"item_id": "b", "publication_key": "p2"}]}
    items = {"a": {"publisher_domain": "www.burgas.bg"},
             "b": {"publisher_domain": "dariknews.bg"}}
    assert story_store.metrics(story, items)["publisher_count"] == 2


def test_the_evidence_gate_and_the_editor_count_share_one_definition():
    """§F: the two can never disagree about what a publisher is."""
    for host in ("www.burgas.bg", "burgas.bg", "m.dariknews.bg", "amp.example.com"):
        assert story_store.publisher_identity(host) == story_research._publisher_identity(host)


def test_several_registry_rows_for_one_domain_resolve_to_every_row():
    """§R1: the answer must not depend on which row happens to sort first."""
    rows = {
        "burgas.bg": [
            {"source_id": "burgas-municipality", "name": "Община Бургас",
             "kind": "official", "factual_authority": True},
            {"source_id": "burgas-cultural-program", "name": "Културна програма — Бургас",
             "kind": "official", "factual_authority": True},
        ]
    }
    resolved = newsroom_run.resolve_publisher_policy(
        "www.burgas.bg", rows, publisher_identity=story_store.publisher_identity
    )
    assert resolved["factual_authority"] is True
    assert resolved["source_ids"] == ["burgas-cultural-program", "burgas-municipality"]
    # §R1: the displayed publisher is the institution, not the accidental first row.
    assert resolved["name"] == "Община Бургас"


def test_an_unknown_publisher_still_gets_no_authority():
    """M4A.1 is untouched: authority is never inherited or invented."""
    resolved = newsroom_run.resolve_publisher_policy(
        "unknown.test", {}, publisher_identity=story_store.publisher_identity
    )
    assert resolved["factual_authority"] is False
    assert resolved["source_ids"] == []


# ---------------------------------------------------------------------------
# §R4 — no terminal research outcome is a generic sentence
# ---------------------------------------------------------------------------


def test_every_research_reason_maps_to_a_distinct_editor_message():
    """§R4: the closed set has no two members that say the same thing."""
    from editor_assistant.workflow import editor_application as app
    from editor_assistant.workflow.workbench import api

    seen = {}
    for reason in story_research.RESEARCH_REASONS:
        refusal = app._research_refusal(story_research.StoryResearchError("x", reason=reason))
        seen[reason] = (type(refusal), str(refusal))
        assert api._MESSAGES[refusal.code] == refusal.default_message
    assert len(set(seen.values())) == len(seen)


def test_the_technical_sentence_is_reachable_only_for_a_technical_failure():
    """§R4: "something broke" must not become the default answer."""
    from editor_assistant.workflow import editor_application as app

    for reason in story_research.RESEARCH_REASONS - {story_research.TECHNICAL_FAILURE}:
        refusal = app._research_refusal(
            story_research.StoryResearchError("detail", reason=reason)
        )
        assert str(refusal) != app.RESEARCH_TECHNICAL_MESSAGE


def test_an_infrastructure_detail_never_reaches_the_editor():
    from editor_assistant.workflow import editor_application as app

    refusal = app._research_refusal(
        story_research.StoryResearchError(
            'Traceback: File "/x/y.py"', reason=story_research.TECHNICAL_FAILURE
        )
    )
    assert "/x/y.py" not in str(refusal)
    assert str(refusal) == app.RESEARCH_TECHNICAL_MESSAGE


def test_the_owner_s_generic_sentence_no_longer_exists():
    """§R4: the exact sentence the owner saw must be gone from the product."""
    from editor_assistant.workflow import editor_application as app
    from editor_assistant.workflow.workbench import api

    assert "Проучването не можа да завърши" not in api._MESSAGES.values()
    for reason in story_research.RESEARCH_REASONS:
        refusal = app._research_refusal(
            story_research.StoryResearchError("x", reason=reason)
        )
        assert "Проучването не можа да завърши" not in str(refusal)


# ---------------------------------------------------------------------------
# §D — the fast Focus
# ---------------------------------------------------------------------------


def test_the_primary_focus_is_filled_and_story_specific():
    focus = focus_suggestions.primary_focus(BURGAS_SOZOPOL, facts=["f"])
    assert focus and "Бургас-Созопол" in focus
    # §D4: no model call, so this must be a pure function of its inputs.
    assert focus == focus_suggestions.primary_focus(BURGAS_SOZOPOL, facts=["f"])


def test_the_primary_focus_drops_the_publisher_suffix():
    focus = focus_suggestions.primary_focus(f"{BURGAS_SOZOPOL} - Община Бургас", facts=[])
    assert "Община Бургас" not in focus


def test_a_story_with_no_usable_subject_yields_no_focus():
    assert focus_suggestions.primary_focus("", facts=[]) == ""
    assert focus_suggestions.alternatives("") == ()


def test_no_generic_focus_alternatives_are_produced():
    """V1.2-G4.3 §C3: the alternatives are gone, and that is the decision.

    The old §D2 contract asked for two or three deterministic variants. A real
    review of generated articles found the opposite problem: they were
    templates that could sit on any story in the desk, so the editor had to
    evaluate a choice that was never a real editorial decision. The brief for
    this slice is explicit - do not render chips unless they are genuinely
    Story-specific, and zero alternatives is acceptable - so the honest
    assertion is that the set is EMPTY, not merely short.
    """
    assert focus_suggestions.alternatives(BURGAS_SOZOPOL, facts=["f"]) == ()


def test_alternatives_never_gate_draft_eligibility():
    """§D4: empty alternatives is a normal outcome, not a failure."""
    assert focus_suggestions.alternatives("   ", facts=[]) == ()


# ---------------------------------------------------------------------------
# §E — the single-source experiment stays isolated
# ---------------------------------------------------------------------------


def _single_source_basis():
    return {
        "evidence_status": "assessed",
        "facts": [{"id": "fact_1", "sourceId": "s1", "text": "X",
                   "source": {"id": "s1", "url": "https://x.test/a", "name": "X"}}],
        "sources": [{"id": "s1", "domain": "x.test", "name": "X",
                     "url": "https://x.test/a"}],
        "gaps": [{"kind": "unresolved", "question": "Нужен е още независим източник.",
                  "blocking": True}],
    }


def test_the_experiment_unlocks_a_single_media_source_with_attribution():
    """V1.2-G4.1 §B3 — this experiment is now the production rule.

    G2.4B measured a single-source attributed Draft and the owner adopted it, so
    the old production gate this experiment compares against is no longer the one
    in force — for this basis the current gate already permits the Draft. The
    experiment's own contribution is therefore no longer a *delta*; the rule that
    actually decides is `draft_material.assess`, and both are asserted here so
    the adoption is visible and cannot drift.
    """
    result = single_source_policy.evaluate(**_single_source_basis())
    # §E4: the experiment speaks only where the gate it compares against refuses,
    # and that gate has since been replaced — for this basis the CURRENT gate
    # already permits the Draft, so the experiment has nothing left to unlock and
    # reports no attribution requirement. That is the correct, honest reading of
    # "the experiment is now redundant because the rule was adopted", and it is
    # asserted here so the redundancy cannot be mistaken for a regression.
    assert result["eligible_now"] is True
    assert result["draft_capable_single"] is False
    assert result["delta"] is False
    assert result["attribution_required"] is False

    # The genuinely single-source case: one opened page, but no promoted fact
    # behind it. This is the prototype fallback §B3 C exists for, and it is the
    # only basis that must carry the attribution requirement.
    basis = _single_source_basis()
    basis["facts"] = []
    decision = draft_material.assess(
        facts=basis["facts"],
        sources=basis["sources"],
        blocking_gaps=[g for g in basis["gaps"] if g.get("blocking")],
    )
    assert decision["eligible"] is True
    assert decision["basis"] == draft_material.SINGLE_SOURCE
    assert decision["attribution"] is True
    assert draft_material.WARNING_SINGLE_SOURCE in decision["warnings"]
    assert draft_material.WARNING_OPEN_GAPS in decision["warnings"]

    # A basis WITH a promoted fact backed by an opened page is the stronger
    # `PROMOTED` path, and must not be asked to carry the single-source caveat.
    promoted = _single_source_basis()
    assert draft_material.assess(
        facts=promoted["facts"],
        sources=promoted["sources"],
        blocking_gaps=[],
    )["attribution"] is False


def test_the_experiment_refuses_an_aggregator_wrapper():
    """§E1: an unresolved aggregator supports no attributed Draft either."""
    basis = _single_source_basis()
    basis["sources"] = [dict(basis["sources"][0], domain="news.google.com")]
    assert single_source_policy.evaluate(**basis)["draft_capable_single"] is False


def test_the_experiment_refuses_a_known_contradiction():
    basis = _single_source_basis()
    basis["gaps"] = basis["gaps"] + [
        {"kind": "conflict", "question": "Източниците се разминават.", "blocking": False}
    ]
    assert single_source_policy.evaluate(**basis)["draft_capable_single"] is False


def test_the_experiment_refuses_incomplete_provenance():
    basis = _single_source_basis()
    basis["facts"] = [dict(basis["facts"][0], sourceId="someone-else")]
    assert single_source_policy.evaluate(**basis)["draft_capable_single"] is False


def test_the_experiment_never_claims_an_already_eligible_story():
    """§E4: the experiment only speaks where the current gate refuses."""
    basis = _single_source_basis()
    basis["gaps"] = []
    result = single_source_policy.evaluate(**basis)
    assert result["eligible_now"] is True
    assert result["delta"] is False
