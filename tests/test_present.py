"""M1.5 Step 2 tests — deterministic presentation cleanup (all 20 required proofs).

Presentation is display-only: nothing here may change SourceItem, fingerprints,
item_state semantics, or outbox identity.
"""

from __future__ import annotations

import pathlib
import sqlite3
from datetime import datetime, timezone

from editor_assistant.models import SourceDef, SourceItem
from editor_assistant.notify.outbox import list_pending
from editor_assistant.notify.present import (
    DISPLAY_EXCERPT_LIMIT,
    MAX_ATTACHMENTS_SHOWN,
    SOURCE_DISPLAY_NAMES,
    attachment_summary,
    clean_body_text,
    clean_excerpt,
    display_source_name,
    extract_display_subject,
    strip_leading_subject,
)
from editor_assistant.notify.render import (
    build_payload,
    format_published_bg_display,
    render_message,
)
from editor_assistant.sources.rss import PARSER_ID
from editor_assistant.state import process_items
from editor_assistant.state.fingerprint import fingerprint_item
from editor_assistant.state.store import TELEGRAM_TEST_DESTINATION

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "rss_burgas_municipality.xml"
SOURCE = SourceDef(
    source_id="burgas-municipal-council",
    canonical_url="https://burgascouncil.org/",
    parser=PARSER_ID,
)
T0 = datetime(2026, 9, 11, 13, 23, 57, tzinfo=timezone.utc)

_CREDIT = "zh.gospodinova Пет. | 11.09.2026г. | 16:23ч."
_BODY = (
    "ДОКЛАДНА ЗАПИСКА 08 - 00 18837 / 11.09.2026 г. от Димитър Николов - кмет на "
    "Община Бургас, относно: Определяне предназначението на общински жилища по чл. 42, "
    "ал. 2 от Закона за общинската собственост "
    f"{_CREDIT} ФАЙЛОВЕ И РЕСУРСИ ВКЛЮЧЕНО В ПРЕДСТОЯЩО ЗАСЕДАНИЕ НА ПОСТОЯННА КОМИСИЯ"
)
_TITLE = "ДОКЛАДНА ЗАПИСКА 08 - 00 18837 / 11.09.2026 г."


def _item(**overrides) -> SourceItem:
    base = {
        "source_id": SOURCE.source_id,
        "source_url": SOURCE.canonical_url,
        "item_url": "https://burgascouncil.org/node/3636",
        "title": _TITLE,
        "published_at": T0,
        "fetched_at": T0,
        "body_text": _BODY,
        "body_links": (
            "https://burgascouncil.org/sites/default/files/2026-09/18837sayt.pdf",
            "https://burgascouncil.org/sites/default/files/2026-09/18837.docx",
        ),
        "author": None,
    }
    return SourceItem(**{**base, **overrides})


# §1/§2 — display names
def test_known_source_maps_to_bg_name():
    assert display_source_name("burgas-municipal-council") == "Общински съвет – Бургас"
    assert "burgas-municipal-council" in SOURCE_DISPLAY_NAMES


def test_unknown_source_falls_back_safely():
    assert display_source_name("no-such-source") == "no-such-source"


# §2/§3 — subject extraction
def test_subject_extracted_after_otnosno():
    subject = extract_display_subject(_TITLE, _BODY)
    assert subject is not None
    assert subject.startswith("Определяне предназначението на общински жилища")
    assert "gospodinova" not in subject
    assert "ФАЙЛОВЕ" not in subject


def test_subject_extraction_case_insensitive():
    body = "някакъв текст ОТНОСНО: предмет на делото"
    assert extract_display_subject(_TITLE, body) == "предмет на делото"


def test_subject_missing_falls_back_to_title():
    payload = build_payload(_item(body_text="текст без маркер"), event_type="NEW", version_no=1)
    assert _TITLE in render_message(payload)


def test_extracted_text_is_source_derived_only():
    body = "Предисловие. ОТНОСНО: Заявени са точно 3 500 лева от бюджета."
    subject = extract_display_subject(_TITLE, body)
    assert subject == "Заявени са точно 3 500 лева от бюджета."


def test_no_empty_headline():
    payload = build_payload(_item(body_text="относно:   "), event_type="NEW", version_no=1)
    assert _TITLE in render_message(payload)


# §4/§5 — boilerplate cleanup + excerpt
def test_known_boilerplate_removed_from_excerpt():
    excerpt = clean_excerpt(_BODY, title=_TITLE)
    assert excerpt is not None
    assert "ФАЙЛОВЕ И РЕСУРСИ" not in excerpt
    assert "ВКЛЮЧЕНО В ПРЕДСТОЯЩО" not in excerpt
    assert "gospodinova" not in excerpt
    assert "Определяне предназначението" in excerpt


def test_normalized_body_text_unchanged():
    item = _item()
    clean_body_text(item.body_text, title=item.title)
    assert item.body_text == _BODY
    assert item.title == _TITLE


def test_fingerprint_unchanged_by_presentation_cleanup():
    before = fingerprint_item(_item())
    _ = (clean_body_text(_BODY, title=_TITLE), extract_display_subject(_TITLE, _BODY))
    after = fingerprint_item(_item())
    assert before == after


def test_clean_excerpt_respects_limit():
    filler = " Изречението е точно колкото трябва. " * 40
    excerpt = clean_excerpt(f"{_TITLE} {_CREDIT} {filler}", title=_TITLE)
    assert excerpt is not None
    assert len(excerpt) <= DISPLAY_EXCERPT_LIMIT + 1
    assert excerpt.endswith("…")


def test_bulgarian_text_remains_intact():
    subject = extract_display_subject(_TITLE, _BODY)
    assert "общински жилища" in subject
    assert "чл. 42, ал. 2" in subject


# §6 — publication time
def test_published_at_bg_format():
    assert format_published_bg_display(T0) == "11.09.2026, 16:23"


def test_missing_published_renders_cleanly():
    assert format_published_bg_display(None) is None
    payload = build_payload(_item(published_at=None), event_type="NEW", version_no=1)
    assert "🕒" not in render_message(payload)


# §7/§8/§9/§10 — attachments and source link
def test_one_attachment_renders_correctly():
    payload = build_payload(
        _item(body_links=("https://x.org/a/b.pdf",)), event_type="NEW", version_no=1
    )
    msg = render_message(payload)
    assert "• PDF — https://x.org/a/b.pdf" in msg
    assert "още" not in msg


def test_three_attachments_renders_correctly():
    links = tuple(f"https://x.org/{i}.pdf" for i in (1, 2, 3))
    payload = build_payload(_item(body_links=links), event_type="NEW", version_no=1)
    msg = render_message(payload)
    assert msg.count("• ") == 3
    assert "още" not in msg


def test_fourteen_attachments_compact():
    links = tuple(
        ["https://x.org/18837sayt.pdf", "https://x.org/18837.doc"]
        + [f"https://x.org/prilozhenie-{i}.xls" for i in range(1, 13)]
    )
    assert len(links) == 14
    visible, hidden = attachment_summary(links)
    assert len(visible) == 3 and hidden == 11
    msg = render_message(build_payload(_item(body_links=links), event_type="NEW", version_no=1))
    assert "+11 още" in msg
    assert "prilozhenie-1.xls" in msg
    assert "prilozhenie-2.xls" not in msg


def test_attachment_order_preserved():
    links = ("https://x.org/a.doc", "https://x.org/b.pdf", "https://x.org/c.xls")
    visible, _ = attachment_summary(links)
    assert [label for label, _ in visible] == ["DOC", "PDF", "XLS"]


def test_attachment_cap_constant_is_three():
    assert MAX_ATTACHMENTS_SHOWN == 3


def test_no_main_attachment_inference():
    links = ("https://x.org/18837sayt.pdf", "https://x.org/18837.doc", "https://x.org/p-1.xls")
    payload = build_payload(_item(body_links=links), event_type="NEW", version_no=1)
    msg = render_message(payload)
    for forbidden in ("Основен документ", "Бюджет", "Приложение 1"):
        assert forbidden not in msg


def test_source_url_remains_present():
    payload = build_payload(_item(), event_type="NEW", version_no=1)
    msg = render_message(payload)
    assert "🔗 Източник:" in msg
    assert payload.item_url in msg


def test_render_deterministic_twice():
    payload = build_payload(_item(), event_type="NEW", version_no=1)
    assert render_message(payload) == render_message(payload)


# §12 — source-truth preservation through the whole render path
def test_payload_snapshot_and_fingerprint_stable_after_render():
    item = _item()
    fingerprint_before = fingerprint_item(item)
    payload = build_payload(item, event_type="NEW", version_no=1)
    _ = render_message(payload)
    assert fingerprint_item(item) == fingerprint_before
    assert payload.title == _TITLE
    assert payload.body_excerpt != clean_excerpt(_BODY, title=_TITLE)


# —— updated M1.4A renderer-expectation coverage (semantics unchanged) ——
def test_render_shape_and_known_fields():
    payload = build_payload(_item(), event_type="NEW", version_no=1)
    msg = render_message(payload)
    assert msg.startswith("🆕 Общински съвет – Бургас")
    assert "🕒 11.09.2026, 16:23" in msg
    assert "🔗 Източник:" in msg
    assert _item().item_url in msg


def test_updated_marker_differs_from_new():
    new_msg = render_message(build_payload(_item(), event_type="NEW", version_no=1))
    upd_msg = render_message(build_payload(_item(), event_type="UPDATED", version_no=2))
    assert new_msg.startswith("🆕")
    assert upd_msg.startswith("🔄")
    assert new_msg != upd_msg


# =====================================================================
# M1.5 Step 4 — headline/excerpt de-duplication (§9 required tests)
# =====================================================================


def test_exact_leading_subject_duplication_removed():
    subj = "Даване на съгласие за учредяване на център"
    text = f"{subj}. Допълнителна информация за бюджета."
    rest = strip_leading_subject(text, subj)
    assert rest is not None and rest.startswith("Допълнителна информация")


def test_case_only_variation_matches():
    subj = "Даване на съгласие за учредяване"
    text = "даване НА съгласие за учредяване на център. Останалото продължава."
    rest = strip_leading_subject(text, subj)
    assert rest is not None and rest.startswith("на център")


def test_whitespace_variation_matches():
    subj = "Определяне предназначението на общински жилища"
    text = "Определяне   предназначението\nна общински жилища по чл. 42. Продължение на текста."
    rest = strip_leading_subject(text, subj)
    print(repr(rest))
    assert rest is not None and rest.startswith("по чл. 42")


def test_otnosno_prefix_removed_conservatively():
    prefix = "от Димитър Николов - кмет на Община Бургас"
    subj = "Определяне предназначението на общински жилища по чл. 42"
    text = f"{prefix}, относно: {subj} от Закона. Останала част на текста."
    rest = strip_leading_subject(text, subj)
    assert rest is not None and rest.startswith("от Закона")


def test_punctuation_variation_at_boundary():
    subj = "Предмет на записката"
    text = "предмет на записката — Следва пълния текст по чл. 3."
    rest = strip_leading_subject(text, subj)
    assert rest is not None and rest.startswith("Следва")


def test_partial_resemblance_preserved():
    subj = "Даване на съгласие за учредяване на център"
    text = "Даване на участие в конкурса за новия проекти. Друг текст."
    assert strip_leading_subject(text, subj) == text


def test_same_words_later_in_body_not_removed():
    subj = "Обновление на план за действие"
    text = "Пълен анализ на делото. В първата година се предвижда обновление на план за действие."
    assert strip_leading_subject(text, subj) == text


def test_unrelated_body_untouched():
    subj = "Бюджет за 2026"
    text = "Статия за културата и образованието в Община Бургас."
    assert strip_leading_subject(text, subj) == text


def test_fully_duplicated_body_produces_no_excerpt():
    subj = "Единствен известен текст без резюме"
    assert strip_leading_subject(f"{subj} ", subj) is None
    assert clean_excerpt(f"{subj}. ", subject=subj) is None


def test_bulgarian_unicode_remains_intact():
    subj = "Определяне предназначението на общински жилища по чл. 42"
    text = "ОПРЕДЕЛЯНЕ ПРЕДНАЗНАЧЕНИЕТО НА ОБЩИНСКИ ЖИЛИЩА ПО ЧЛ. 42 от закона. Оставай крайно важна част."
    rest = strip_leading_subject(text, subj)
    assert rest == "от закона. Оставай крайно важна част."


def test_source_item_unchanged_after_dedup():
    item = _item()
    before = (item.title, item.body_text, item.body_links, item.published_at)
    _ = strip_leading_subject(
        item.body_text or "", extract_display_subject(item.title, item.body_text)
    )
    assert (item.title, item.body_text, item.body_links, item.published_at) == before


def test_fingerprint_unchanged_after_dedup():
    item = _item()
    fp = fingerprint_item(item)
    _ = strip_leading_subject(
        item.body_text or "", extract_display_subject(item.title, item.body_text)
    )
    assert fingerprint_item(item) == fp


def test_step4_content_hash_unaffected(tmp_path):
    item = _item()
    db = tmp_path / "s.sqlite3"
    process_items([item], T0, db_path=db, destination=TELEGRAM_TEST_DESTINATION)
    conn = sqlite3.connect(db)
    before = conn.execute(
        "SELECT content_hash FROM item_state WHERE item_url = ?", (item.item_url,)
    ).fetchone()[0]
    conn.close()
    payload = list_pending(db, destination=TELEGRAM_TEST_DESTINATION)[0].payload
    _ = render_message(payload)
    conn = sqlite3.connect(db)
    after = conn.execute(
        "SELECT content_hash FROM item_state WHERE item_url = ?", (item.item_url,)
    ).fetchone()[0]
    conn.close()
    assert before == after


def test_step4_render_deterministic():
    payload = build_payload(_item(), event_type="NEW", version_no=1)
    assert render_message(payload) == render_message(payload)


def test_step4_render_shows_subject_once():
    payload = build_payload(_item(), event_type="NEW", version_no=1)
    msg = render_message(payload)
    subj = extract_display_subject(payload.title, payload.body_excerpt)
    assert subj is not None
    assert msg.count(subj) == 1  # headline only — no duplicate in the excerpt
    assert "от Димитър Николов" not in msg  # admin prefix + relation marker gone
