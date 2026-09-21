# M4C Story Identity — Manual Review Pack

Generated from a **real isolated collection** (2026-09-21) into a throwaway `NEWSROOM_DIR`; no production state was touched.

## Corpus

- source items (discovery rows): **123**
- unique `publication_key`s: **113**
- exact-duplicate rows collapsed: **10**
- deterministic `SAME_STORY` merges: **1**
- ambiguous shortlist items: **102**
- story count (deterministic-only build): **112**

> The model's own answer is **not** ground truth. Everything below is a sample for a human to judge; `за преглед` marks uncertain cases.

## 1. Exact publication duplicates (8 groups, first 5 shown)

One published article found through several discovery monitors. The raw rows stay; the story counts discoveries and publications separately.

### `p535f5a135563e91` — 2 discoveries, 1 publication
- **Временно затварят вътрешния път Приморско–Китен - БНР** — bnr.bg · публикувано 2026-09-19 10:59 · открит от `bnr-burgas`
- **Временно затварят вътрешния път Приморско–Китен - БНР** — bnr.bg · публикувано 2026-09-19 10:59 · открит от `primorsko-municipality`
  - publishers in group: 1 (same publisher, different monitors)

### `pccd0fb121e8060c` — 2 discoveries, 1 publication
- **Започна нов етап от реконструцията на вътрешния път Приморско-Китен - БНР** — bnr.bg · публикувано 2026-09-18 11:00 · открит от `bnr-burgas`
- **Започна нов етап от реконструцията на вътрешния път Приморско-Китен - БНР** — bnr.bg · публикувано 2026-09-18 11:00 · открит от `primorsko-municipality`
  - publishers in group: 1 (same publisher, different monitors)

### `p41759f913f174db` — 2 discoveries, 1 publication
- **Община Бургас дава сцена на новото поколение артисти с програма „Дебюти“ - Община Бургас** — www.burgas.bg · публикувано 2026-09-18 13:23 · открит от `google-news-burgas-region`
- **Община Бургас дава сцена на новото поколение артисти с програма „Дебюти“ - Община Бургас** — www.burgas.bg · публикувано 2026-09-18 13:23 · открит от `burgas-municipality`
  - publishers in group: 1 (same publisher, different monitors)

### `pfd992d1965b166d` — 3 discoveries, 1 publication
- **Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg** — bnrnews.bg · публикувано 2026-09-20 12:31 · открит от `google-news-burgas-region`
- **Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg** — bnrnews.bg · публикувано 2026-09-20 12:31 · открит от `burgas-municipality`
- **Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg** — bnrnews.bg · публикувано 2026-09-20 12:31 · открит от `bnr-burgas`
  - publishers in group: 1 (same publisher, different monitors)

### `p86f79af16e914e1` — 2 discoveries, 1 publication
- **Почистват проблемни участъци по река Дяволска край Ясна Поляна - Черноморски фар** — www.faragency.bg · публикувано 2026-09-20 14:43 · открит от `primorsko-municipality`
- **Почистват проблемни участъци по река Дяволска край Ясна Поляна - Черноморски фар** — www.faragency.bg · публикувано 2026-09-20 14:43 · открит от `chernomorski-far`
  - publishers in group: 1 (same publisher, different monitors)

## 2. Cross-publisher `SAME_STORY` merges (deterministic)

### Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - bnrnews.bg
- **Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - bnrnews.bg** — bnrnews.bg · публикувано 2026-09-21 05:31 · открит от `google-news-burgas-region`
  - merged into story with:
      - Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - БНР (bnr.bg)
      - Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - bnrnews.bg (bnrnews.bg)
  - deterministic score: title=0.8 distinctive=0.8889 hours=0.01 (reason: near-identical title (0.8) + distinctive overlap (0.8889) + close publication time)

## 3. Semantic relation probe (ambiguous shortlist, capped)

Only the first **10** ambiguous items were probed, with the `role="story"` pool (`OPENROUTER_STORY_MODEL`). Provider/model: qwen free tier.

### Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg — `DIFFERENT_STORY`
- **Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg** — bnrnews.bg · публикувано 2026-09-20 12:31 · открит от `bnr-burgas`
  - compared with representative: Общинският съвет гласува бюджета на Бургас - bnrnews.bg
  - shortlist score: 0.1984 (title=0.1111, distinctive=0.1429, hours=16.49)
  - semantic: same_event=False material_change=False anchors=['Община Бургас']
  - reason: Новата публикация е за програма за млади и начинаещи творци, а съществуващата история е за гласуване на бюджета на Бургас.

### „Писана история“ среща ученици от Бургас с почерка на българските герои - БНР — `DIFFERENT_STORY`
- **„Писана история“ среща ученици от Бургас с почерка на българските герои - БНР** — bnr.bg · публикувано 2026-09-18 09:30 · открит от `bnr-burgas`
  - compared with representative: Илин Димитров: Очакваме 5 млн. туристи за целия сезон - БНР
  - shortlist score: 0.1688 (title=0.0625, distinctive=0.125, hours=30.0)
  - semantic: same_event=False material_change=False anchors=[]
  - reason: Различни теми: една е за културно събитие в Бургас, другата е за очаквания брой туристи.

### Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - БНР — `DIFFERENT_STORY`
- **Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - БНР** — bnr.bg · публикувано 2026-09-21 05:31 · открит от `bnr-burgas`
  - compared with representative: Илин Димитров: Очакваме 5 млн. туристи за целия сезон - БНР
  - shortlist score: 0.1627 (title=0.0588, distinctive=0.1111, hours=38.03)
  - semantic: same_event=False material_change=False anchors=['БНР']
  - reason: Новата публикация е за флашмоб и подкаст за Световния ден за болестта на Алцхаймер, а съществуващата история е за очаквания брой туристи за сезона.

### В "Ден до пладне" на 19 септември: - БНР — `DIFFERENT_STORY`
- **В "Ден до пладне" на 19 септември: - БНР** — bnr.bg · публикувано 2026-09-19 06:55 · открит от `bnr-burgas`
  - compared with representative: Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - bnrnews.bg
  - shortlist score: 0.3033 (title=0.1667, distinctive=0.4, hours=46.61)
  - semantic: same_event=False material_change=False anchors=[]
  - reason: Новата публикация е общо за епизод от „Ден до пладне“ на 19 септември, докато съществуващата история е за флашмоб и подкаст за Световния ден за болестта на Алцхаймер на 21 септември.

### Възможни прекъсвания на водоподаването в Елхово - БНР — `DIFFERENT_STORY`
- **Възможни прекъсвания на водоподаването в Елхово - БНР** — bnr.bg · публикувано 2026-09-20 22:42 · открит от `bnr-burgas`
  - compared with representative: В "Ден до пладне" на 19 септември: - БНР
  - shortlist score: 0.2156 (title=0.1111, distinctive=0.2, hours=39.78)
  - semantic: same_event=False material_change=False anchors=['БНР']
  - reason: Нова публикация е за възможни прекъсвания на водоподаването в Елхово, а съществуващата е само за епизод на „Ден до пладне“ без конкретна връзка.

### Очаквайте в "Акценти" на 21 септември! - БНР — `DIFFERENT_STORY`
- **Очаквайте в "Акценти" на 21 септември! - БНР** — bnr.bg · публикувано 2026-09-21 03:30 · открит от `bnr-burgas`
  - compared with representative: В "Ден до пладне" на 19 септември: - БНР
  - shortlist score: 0.345 (title=0.25, distinctive=0.4, hours=44.58)
  - semantic: same_event=False material_change=False anchors=['БНР']
  - reason: Различни програми и дати: „Акценти“ на 21 септември срещу „Ден до пладне“ на 19 септември; няма общо събитие.

### Станко Киров и изкуството да превръщаш ракитата в изкуство - БНР — `DIFFERENT_STORY`
- **Станко Киров и изкуството да превръщаш ракитата в изкуство - БНР** — bnr.bg · публикувано 2026-09-20 13:30 · открит от `bnr-burgas`
  - compared with representative: В "Ден до пладне" на 19 септември: - БНР
  - shortlist score: 0.1883 (title=0.0909, distinctive=0.1429, hours=30.58)
  - semantic: same_event=False material_change=False anchors=['БНР']
  - reason: Новата публикация е за Станко Киров и ракитата, докато съществуващата е общо заглавие на програма „Ден до пладне“ без конкретна връзка с това събитие.

### 21 български фолклорни групи от чужбина се събраха в Бургас - БНР — `DIFFERENT_STORY`
- **21 български фолклорни групи от чужбина се събраха в Бургас - БНР** — bnr.bg · публикувано 2026-09-18 19:07 · открит от `bnr-burgas`
  - compared with representative: Очаквайте в "Акценти" на 21 септември! - БНР
  - shortlist score: 0.2857 (title=0.2, distinctive=0.2857, hours=56.38)
  - semantic: same_event=False material_change=False anchors=[]
  - reason: Съществуващата публикация е общо анонсиране за ефира на 21 септември, а новата е конкретна новина за фолклорни групи в Бургас; няма достатъчно общи детайли за едно и също събитие.

### България ще участва със 127 състезатели на Световното първенство по кикбокс във всички дисциплини за деца, кадети, юноши и девойки в Италия - БТА — `DIFFERENT_STORY`
- **България ще участва със 127 състезатели на Световното първенство по кикбокс във всички дисциплини за деца, кадети, юноши и девойки в Италия - БТА** — www.bta.bg · публикувано 2026-09-20 14:11 · открит от `bta-burgas`
  - compared with representative: Събитийният туризъм трябва да се превърне в национална политика, коментира зам.-кметът на Бургас Манол Тодоров - БТА
  - shortlist score: 0.1414 (title=0.04, distinctive=0.0714, hours=22.78)
  - semantic: same_event=False material_change=False anchors=[]
  - reason: Новата публикация е за българското участие на Световното първенство по кикбокс в Италия, а съществуващата история е за коментар на зам.-кмет на Бургас относно събитийния туризъм.

### България отново беше намесена в нападките между управляващите и опозицията в Северна Македония - БТА — `DIFFERENT_STORY`
- **България отново беше намесена в нападките между управляващите и опозицията в Северна Македония - БТА** — www.bta.bg · публикувано 2026-09-20 12:22 · открит от `bta-burgas`
  - compared with representative: Събитийният туризъм трябва да се превърне в национална политика, коментира зам.-кметът на Бургас Манол Тодоров - БТА
  - shortlist score: 0.1583 (title=0.05, distinctive=0.1111, hours=20.97)
  - semantic: same_event=False material_change=False anchors=['БТА']
  - reason: Новата публикация е за политически напрежения между управляващите и опозицията в Северна Македония, докато съществуващата история е за събитийния туризъм в Бургас.

## 4. `NEW_DEVELOPMENT` / `RELATED_BACKGROUND` examples

**None in this corpus.** No probed pair was a materially new development or related background, so both relations are `NOT_EVALUATED` here — the lifecycle rules are covered by hermetic tests instead (`tests/test_story_identity.py::test_new_development_reopens_a_seen_story`).

## 5. Near-miss / `DIFFERENT_STORY` examples (10)

Similar-looking pairs that must **not** merge. These are the dangerous false-merge candidates; every one below was kept separate.

### near-miss #1: Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg
- **Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg** — bnrnews.bg · публикувано 2026-09-20 12:31 · открит от `bnr-burgas`
  - candidate shortlisted against: Общинският съвет гласува бюджета на Бургас - bnrnews.bg
  - score 0.1984 · shared tokens ['bnrnews']
  - semantic answer: DIFFERENT_STORY — Новата публикация е за програма за млади и начинаещи творци, а съществуващата история е за гласуване на бюджета на Бургас.

### near-miss #2: „Писана история“ среща ученици от Бургас с почерка на българските герои - БНР
- **„Писана история“ среща ученици от Бургас с почерка на българските герои - БНР** — bnr.bg · публикувано 2026-09-18 09:30 · открит от `bnr-burgas`
  - candidate shortlisted against: Илин Димитров: Очакваме 5 млн. туристи за целия сезон - БНР
  - score 0.1688 · shared tokens ['бнр']
  - semantic answer: DIFFERENT_STORY — Различни теми: една е за културно събитие в Бургас, другата е за очаквания брой туристи.

### near-miss #3: Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - БНР
- **Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - БНР** — bnr.bg · публикувано 2026-09-21 05:31 · открит от `bnr-burgas`
  - candidate shortlisted against: Илин Димитров: Очакваме 5 млн. туристи за целия сезон - БНР
  - score 0.1627 · shared tokens ['бнр']
  - semantic answer: DIFFERENT_STORY — Новата публикация е за флашмоб и подкаст за Световния ден за болестта на Алцхаймер, а съществуващата история е за очаквания брой туристи за сезона.

### near-miss #4: В "Ден до пладне" на 19 септември: - БНР
- **В "Ден до пладне" на 19 септември: - БНР** — bnr.bg · публикувано 2026-09-19 06:55 · открит от `bnr-burgas`
  - candidate shortlisted against: Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - bnrnews.bg
  - score 0.3033 · shared tokens ['бнр', 'ден']
  - semantic answer: DIFFERENT_STORY — Новата публикация е общо за епизод от „Ден до пладне“ на 19 септември, докато съществуващата история е за флашмоб и подкаст за Световния ден за болестта на Алцхаймер на 21 септември.

### near-miss #5: Възможни прекъсвания на водоподаването в Елхово - БНР
- **Възможни прекъсвания на водоподаването в Елхово - БНР** — bnr.bg · публикувано 2026-09-20 22:42 · открит от `bnr-burgas`
  - candidate shortlisted against: В "Ден до пладне" на 19 септември: - БНР
  - score 0.2156 · shared tokens ['бнр']
  - semantic answer: DIFFERENT_STORY — Нова публикация е за възможни прекъсвания на водоподаването в Елхово, а съществуващата е само за епизод на „Ден до пладне“ без конкретна връзка.

### near-miss #6: Очаквайте в "Акценти" на 21 септември! - БНР
- **Очаквайте в "Акценти" на 21 септември! - БНР** — bnr.bg · публикувано 2026-09-21 03:30 · открит от `bnr-burgas`
  - candidate shortlisted against: В "Ден до пладне" на 19 септември: - БНР
  - score 0.345 · shared tokens ['бнр', 'септември']
  - semantic answer: DIFFERENT_STORY — Различни програми и дати: „Акценти“ на 21 септември срещу „Ден до пладне“ на 19 септември; няма общо събитие.

### near-miss #7: Станко Киров и изкуството да превръщаш ракитата в изкуство - БНР
- **Станко Киров и изкуството да превръщаш ракитата в изкуство - БНР** — bnr.bg · публикувано 2026-09-20 13:30 · открит от `bnr-burgas`
  - candidate shortlisted against: В "Ден до пладне" на 19 септември: - БНР
  - score 0.1883 · shared tokens ['бнр']
  - semantic answer: DIFFERENT_STORY — Новата публикация е за Станко Киров и ракитата, докато съществуващата е общо заглавие на програма „Ден до пладне“ без конкретна връзка с това събитие.

### near-miss #8: 21 български фолклорни групи от чужбина се събраха в Бургас - БНР
- **21 български фолклорни групи от чужбина се събраха в Бургас - БНР** — bnr.bg · публикувано 2026-09-18 19:07 · открит от `bnr-burgas`
  - candidate shortlisted against: Очаквайте в "Акценти" на 21 септември! - БНР
  - score 0.2857 · shared tokens ['21', 'бнр']
  - semantic answer: DIFFERENT_STORY — Съществуващата публикация е общо анонсиране за ефира на 21 септември, а новата е конкретна новина за фолклорни групи в Бургас; няма достатъчно общи детайли за едно и също събитие.

### near-miss #9: България ще участва със 127 състезатели на Световното първенство по кикбокс във всички дисциплини за деца, кадети, юноши и девойки в Италия - БТА
- **България ще участва със 127 състезатели на Световното първенство по кикбокс във всички дисциплини за деца, кадети, юноши и девойки в Италия - БТА** — www.bta.bg · публикувано 2026-09-20 14:11 · открит от `bta-burgas`
  - candidate shortlisted against: Събитийният туризъм трябва да се превърне в национална политика, коментира зам.-кметът на Бургас Манол Тодоров - БТА
  - score 0.1414 · shared tokens ['бта']
  - semantic answer: DIFFERENT_STORY — Новата публикация е за българското участие на Световното първенство по кикбокс в Италия, а съществуващата история е за коментар на зам.-кмет на Бургас относно събитийния туризъм.

### near-miss #10: България отново беше намесена в нападките между управляващите и опозицията в Северна Македония - БТА
- **България отново беше намесена в нападките между управляващите и опозицията в Северна Македония - БТА** — www.bta.bg · публикувано 2026-09-20 12:22 · открит от `bta-burgas`
  - candidate shortlisted against: Събитийният туризъм трябва да се превърне в национална политика, коментира зам.-кметът на Бургас Манол Тодоров - БТА
  - score 0.1583 · shared tokens ['бта']
  - semantic answer: DIFFERENT_STORY — Новата публикация е за политически напрежения между управляващите и опозицията в Северна Македония, докато съществуващата история е за събитийния туризъм в Бургас.

## 6. Suspicious / uncertain auto-merges

### Общинският съвет гласува бюджета на Бургас - bnrnews.bg
  - members: 3 · needs_review=False
    - `ORIGIN` / first_item — Общинският съвет гласува бюджета на Бургас - bnrnews.bg (bnrnews.bg)
    - `SAME_STORY` / exact_publication — Общинският съвет гласува бюджета на Бургас - bnrnews.bg (bnrnews.bg)
    - `SAME_STORY` / exact_publication — Общинският съвет гласува бюджета на Бургас - bnrnews.bg (bnrnews.bg)

### Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg
  - members: 3 · needs_review=True
    - `ORIGIN` / first_item — Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg (bnrnews.bg)
    - `SAME_STORY` / exact_publication — Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg (bnrnews.bg)
    - `SAME_STORY` / exact_publication — Община Бургас стартира програма "Дебюти" за млади и начинаещи творци - bnrnews.bg (bnrnews.bg)

### „Писана история“ среща ученици от Бургас с почерка на българските герои - БНР
  - members: 1 · needs_review=True
    - `ORIGIN` / first_item — „Писана история“ среща ученици от Бургас с почерка на българските герои - БНР (bnr.bg)

### Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - БНР
  - members: 2 · needs_review=True
    - `ORIGIN` / first_item — Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - БНР (bnr.bg)
    - `SAME_STORY` / deterministic_title — Провеждат флашмоб и подкаст на живо за Световния ден за болестта на Алцхаймер - bnrnews.bg (bnrnews.bg)

### В "Ден до пладне" на 19 септември: - БНР
  - members: 1 · needs_review=True
    - `ORIGIN` / first_item — В "Ден до пладне" на 19 септември: - БНР (bnr.bg)

## Human review checklist

- [ ] Any group in §1 that is NOT the same article
- [ ] Any merge in §2 that hides a distinct event
- [ ] Any near-miss in §5 that should have merged
- [ ] `за преглед` stories needing an editor split/merge

