# M4B — Daily Inbox UX (report)

**Status 2026-09-20: BUILT, LIVE-PROVEN, awaiting review/freeze.**
Scope: `m4/HARNESS_PROMPT_M4A1_SOURCE_PACK_M4B_INBOX.md` PART B.

One inbox item is still **one collected source item** — no story identity, no
clustering, no AI ranking, no scores.

## 1. The daily mental model (B1)

The page answers *«Какво ново има и какво трябва да погледна?»*:

```text
Днес: нови N · прегледани N · игнорирани N · източници с проблем N (показани M от филтъра)
```

Permanent reminder on the page: these are collected **candidates, not evidence**
and nothing here is factually verified.

## 2. Inbox item (B2/B7)

Each item shows the headline (opens the source in a new tab), the source name,
source kind, priority, published time, discovered time and a one-line normalized
summary. Actions are the three obvious ones — **Прегледан**, **Игнорирай**,
**Отвори източника**. Internal ids stay hidden: `item_id` only travels in a
hidden form field, never in visible text.

## 3. Filters (B3)

Practical only: status (`Нови` / `Всички` / `Прегледани` / `Игнорирани`), source,
source kind, priority, date, and authority (Официални / Само наблюдение). No
semantic/topic filters before M4C.

## 4. Noise control (B4)

The default view is **NEW**. Results are paged (50 per page, hard cap 200) so a
busy morning cannot render an unbounded page. Stored items are never dropped by a
filter, and dedup stays exact-identity (`item_id`) — no fuzzy matching.

## 5. Collection control (B5/B6)

**«Събери новите сега»** delegates to the exact one-shot service cron calls
(`newsroom_run.collect`) — the UI owns no collection logic. **«Пробен преглед (без
мрежа)»** runs the same service in dry-run. The result is reported back
(`Събрани N нови · вече известни N · грешки N · филтрирани по домейн N`), and the
section shows **Последно събиране** plus a readable list of **Източници с проблем**
(source name + last error), never a raw traceback.

Both the button and the cron path take the shared collection lock, so they can
never write the inbox/health stores concurrently.

### Recommended cron schedule (the operator installs it; the repo schedules nothing)

`Europe/Sofia`, four light runs a day — early morning, lunch, late afternoon,
evening:

```bash
crontab -e
# 07:00, 12:00, 16:00, 20:00 Sofia time
0 7,12,16,20 * * * cd /home/test/media && PYTHONPATH=src /usr/bin/python3 -m editor_assistant.workflow.cli newsroom collect >> var/newsroom/cron.log 2>&1
```

Exit codes: `0` ok · `1` at least one source failed (the successful sources keep
their items) · `3` another run holds the lock.

## 6. Visual direction (B7)

Calm editor-first cards: readable headline, source badge, time, status badge,
one-line summary, few obvious actions. Bulgarian labels everywhere; engineering
labels are gone from the daily surface. A source that is disabled, muted, or has a
blocked domain is described in editor language («Изключен», «Заглушен до …»,
«забранен домейн»).

## 7. Live proof (2026-09-20, isolated `/tmp/m4a1` runtime)

```text
GET /inbox                              -> 200; summary counts, «Събери новите сега»,
                                           «Пробен преглед», candidate-not-evidence note
GET /inbox?status=all&source=bnr-burgas -> 200; only that source's items
POST /inbox action=collect_preview      -> 303 «Пробен преглед: 30 източника, 30 заявки (без мрежа)»
POST /inbox action=collect              -> 303 «Събрани N нови · вече известни N · грешки 0 …»
POST /inbox action=status IGNORED       -> 303 «Отбелязано.»; item leaves the default NEW view
problems section                        -> lists a FAILED source with its last error
```

Offline tests additionally pin: default view = NEW, status/source filters,
pagination, the collect button delegating to the shared service (dry-run flag
included), a readable refusal for an unknown item, and the source-problems block.

## 8. What was deliberately NOT added (B8)

No story clustering, no `NEW_STORY` / `NEW_DEVELOPMENT`, no semantic duplicate
detection, no AI ranking, no angle generation, no automatic research, no drafting,
no Telegram, no recommendation scores. A structural test
(`tests/test_default_sources.py::test_no_ai_or_story_identity_tokens_in_the_newsroom_stack`)
fails if any of those tokens appears as an identifier in the newsroom modules.

## 9. Verdict

```text
DAILY_INBOX_ENGINEERING = PROVEN
EDITORIAL_EFFECTIVENESS = PENDING   (still the human editor's call)
```
