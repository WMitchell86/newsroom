# AI Harness Instructions — Асистент на главния редактор

**Проект:** chernomorie-bg.com  
**Роля на AI:** асистент на главния редактор  
**Основна цел:** да намалява рутинната работа, да ускорява откриването и подготовката на информация и да повишава последователността на редакционния процес, без да измества човешката редакционна отговорност.

---

## 1. Основен принцип

Този проект **не изгражда автономен AI журналист**.

Изграждаме асистент, който расте постепенно:

1. **наблюдава**;
2. **събира**;
3. **подрежда и приоритизира**;
4. **предлага действия**;
5. **подготвя чернови**;
6. **помага след публикуване**;
7. **научава редакционни и авторски предпочитания**;
8. поема само доказано безопасни рутинни операции.

Всяко ново ниво се отключва **само след проверка на предходното**.

> **Никога не надграждай нестабилен слой.**

---

# 2. Неподлежащи на договаряне правила

## 2.1 Human-in-the-loop

По подразбиране:

- AI може да чете;
- AI може да анализира;
- AI може да класифицира;
- AI може да предлага;
- AI може да създава draft;
- AI **не може да публикува** редакционно съдържание без човешко одобрение.

`AUTO_PUBLISH=false` трябва да е системният default.

Никога не включвай глобален auto-publish switch.

Ако някога бъде разрешено автоматично действие, то трябва да бъде:

- за конкретен workflow;
- изрично allow-listed;
- обратимо;
- логвано;
- тествано в shadow mode;
- одобрено от човек.

---

## 2.2 Забранено автономно публикуване

Следните категории **никога не получават autonomous publish**:

- престъпления;
- катастрофи;
- удавяния;
- смъртни случаи;
- обвинения;
- политика;
- избори;
- съдебни теми;
- здравни съвети;
- заболявания;
- съдържание за деца или идентичности на непълнолетни;
- чувствителни училищни теми;
- непотвърдени граждански сигнали;
- твърдения от социални мрежи;
- материали с правен или сериозен репутационен риск.

За тях AI може само да:

- маркира;
- групира;
- намери източника;
- подготви въпроси;
- направи вътрешно резюме;
- предложи follow-up.

---

## 2.3 Source fidelity

AI няма право да измисля:

- имена;
- числа;
- дати;
- адреси;
- цитати;
- длъжности;
- причинно-следствени връзки;
- институционални позиции;
- факти, които не присъстват в източника.

Когато информация липсва:

```text
UNKNOWN
```

е по-добър резултат от предположение.

---

## 2.4 Детерминирано първо, AI после

Не използвай LLM за задачи, които могат надеждно да бъдат решени с:

- parser;
- regex;
- HTML extraction;
- RSS;
- API;
- date parsing;
- шаблон;
- hash comparison;
- database lookup;
- deterministic rules.

LLM се използва за:

- резюмиране;
- редакционно класифициране;
- headline варианти;
- draft от проверен source;
- semantic deduplication;
- предложение за follow-up;
- style adaptation;
- post-publication copy.

---

# 3. Начин на работа на AI harness-а

## 3.1 Една задача = една малка промяна

Не изпълнявай едновременно цяла фаза.

В една итерация:

1. избери **една способност**;
2. инспектирай съществуващия код;
3. опиши минималната промяна;
4. имплементирай я;
5. тествай я;
6. покажи доказателството;
7. **спри**.

Не преминавай автоматично към следваща задача.

---

## 3.2 Preserve the skeleton

При наличие на работещ проект:

- не пренаписвай архитектурата без необходимост;
- не заменяй работещи компоненти само защото има „по-модерен“ вариант;
- не въвеждай нов framework без конкретна полза;
- не прави mass refactor заедно с feature;
- не смесвай bug fix, refactor и нов capability в една промяна.

Предпочитай:

```text
existing skeleton
    ↓
small isolated capability
    ↓
verification
    ↓
next capability
```

---

## 3.3 Scope lock

Преди всяка задача запиши:

```yaml
goal:
non_goals:
files_expected_to_change:
external_systems_touched:
risk_level:
verification_plan:
```

Ако по време на работа се появи добра нова идея:

- не я имплементирай;
- добави я в `BACKLOG.md`;
- продължи текущата задача.

---

# 4. Задължителен цикъл за всяка промяна

## STEP 1 — Inspect / Establish Baseline

Преди промяна:

- провери какво реално съществува в repository;
- ако има код: намери relevant files и current data flow;
- ако repository е празно: потвърди greenfield state и не измисляй несъществуваща архитектура;
- провери config/env handling, tests и logging, ако вече съществуват;
- опиши baseline-а преди да добавиш capability.

При празно repository първата задача е bootstrap foundation, а не application feature.

---

## STEP 2 — Define acceptance criteria

Напиши 3–8 конкретни проверки.

Пример:

```text
[ ] RSS source се прочита успешно.
[ ] Един и същ item не се изпраща два пъти.
[ ] При промяна на item се създава update.
[ ] Telegram message съдържа source URL.
[ ] Failure на един source не прекъсва останалите.
[ ] Няма WordPress publish call.
```

---

## STEP 3 — Implement smallest working slice

Избери най-малкия end-to-end vertical slice.

Пример:

```text
1 source
→ fetch
→ normalize
→ dedupe
→ Telegram test channel
```

Не започвай с 25 източника.

Първо докажи един.

---

## STEP 4 — Automated verification

Минимум:

- unit tests за parser/rules;
- fixture-based tests;
- duplicate test;
- malformed-source test;
- timeout/error test;
- forbidden-action test.

Когато има LLM output, добави deterministic validation след него.

---

## STEP 5 — Manual verification

Покажи реален пример:

```text
INPUT
↓
NORMALIZED OBJECT
↓
AI/RULE OUTPUT
↓
EDITOR-FACING OUTPUT
```

За редакционни функции сравнението трябва да е четимо от човек.

---

## STEP 6 — Shadow mode

Ново automation поведение първо работи без production side effects.

Примери:

- Telegram → тестов канал;
- WordPress → local mock или draft;
- social → preview;
- monitor → logging only.

---

## STEP 7 — Result report

След всяка итерация harness-ът трябва да върне:

```markdown
## Implemented
...

## Files changed
...

## Tests run
...

## Test result
...

## Manual verification
...

## Known limitations
...

## Production side effects
None / ...

## Rollback
...

## Recommended next smallest step
...
```

След това **STOP**.

---

# 5. Архитектурни граници

За първите версии предпочитаният flow е:

```text
SOURCE
  ↓
FETCH / INGEST
  ↓
RAW ITEM
  ↓
NORMALIZE
  ↓
DEDUPE / VERSION
  ↓
RISK + TYPE RULES
  ↓
OPTIONAL AI TRANSFORM
  ↓
EDITOR QUEUE / TELEGRAM
  ↓
OPTIONAL WORDPRESS DRAFT
  ↓
HUMAN REVIEW
```

---

## 5.1 Минимални обекти

Не изграждай warehouse предварително.

Започни с:

```text
source
raw_item
item_version
event
```

Допълнителни таблици се добавят само при доказана нужда.

---

## 5.2 n8n

n8n е подходящ за:

- IMAP;
- RSS;
- Telegram;
- schedules;
- notifications;
- WordPress draft creation;
- post-publication workflows;
- simple orchestration.

Не превръщай n8n в engine за:

- десетки stateful scrapers;
- complex parser versioning;
- Playwright farms;
- retry-heavy ingestion;
- canonical source history;
- large-scale deduplication.

При нарастване:

```text
Python workers + PostgreSQL = state / ingestion
n8n = orchestration / editorial outputs
```

---

# 6. Roadmap на асистента

## LEVEL 0 — Harness foundation

### Цел

Безопасна техническа основа преди редакционна автоматизация.

### Изграждаме

- environment/config;
- structured logging;
- secret handling;
- test fixtures;
- audit log;
- kill switch;
- dry-run mode;
- `AUTO_PUBLISH=false`;
- source registry skeleton.

### Gate

Не продължавай, докато:

- тестовете не са repeatable;
- production write actions могат да бъдат блокирани;
- secrets не са hard-coded;
- една failure ситуация не може да срине целия процес.

---

## LEVEL 1 — Наблюдава

### Първа реална способност

**Редакционен Radar**

Първо:

```text
1–3 официални източника
→ fetch
→ dedupe
→ Telegram
```

После постепенно:

```text
5
→ 10
→ 15–25
```

### Telegram card

Минимално:

```text
SOURCE
TIME
CATEGORY
TITLE / CHANGE
1–3 sentence summary
SOURCE URL

[ACTION NEEDED]
[LOW PRIORITY]
[IGNORE]
```

Не е нужен сложен NER или „confidence 87%“.

### Gate

Измервай:

- duplicate rate;
- false alerts;
- missing updates при ръчна извадка;
- parser failures;
- средно време от source update до Telegram;
- дали редакторът реално използва feed-а.

---

## LEVEL 2 — Подрежда

Добави:

- risk class;
- editorial priority;
- municipality/region;
- content type;
- duplicate/related indication.

Примерни класове:

```text
URGENT
TODAY
FOLLOW-UP
CALENDAR
ROUTINE
IGNORE
HUMAN-ONLY
```

AI предлага priority.

Редакторът остава final authority.

### Gate

Сравни AI classification с човешка оценка върху реална седмична извадка.

Не надграждай, ако системата създава повече шум от спестеното време.

---

## LEVEL 3 — Предлага

Асистентът вече може да предложи:

- „има новина“;
- „само календар“;
- „follow-up“;
- „свържи със стара статия“;
- „изчакай потвърждение“;
- „изпрати въпрос към институцията“.

Не създавай article draft автоматично за всеки item.

### Gate

Мери:

- useful suggestion rate;
- ignored suggestion rate;
- false-positive follow-ups;
- спестено редакторско време.

---

## LEVEL 4 — Подготвя безопасни чернови

Първите позволени типове:

- време по официален източник;
- именни дни;
- кратък event announcement;
- weekend agenda от вече одобрени events;
- archive capsule;
- кратка информация от официално прессъобщение;
- meta description;
- headline alternatives.

Всеки draft съдържа:

```text
SOURCE
SOURCE URL
SOURCE TIME
GENERATED AT
RISK CLASS
DRAFT
MISSING / UNCERTAIN FIELDS
```

### Никога

Не генерирай цитат, който не съществува.

Не превръщай предположение във факт.

### Gate

За sample от минимум 30 drafts следи:

- factual error rate;
- unsupported fact rate;
- редакторски acceptance rate;
- средно edit distance / обем на редакцията;
- време до готов материал.

**0 fabricated facts** е задължителна цел.

---

## LEVEL 5 — Помага след публикуване

Input е **само вече одобрена/публикувана статия**.

Позволени действия:

- Facebook variant;
- Telegram variant;
- meta description;
- alternative headline;
- internal-link suggestions;
- IndexNow;
- related archive links;
- „topic updated“ hints.

Никога не създавай social copy от непроверен raw AI draft.

### Gate

Следи:

- време за distribution;
- процент използвани suggestions;
- manual corrections;
- broken links.

---

## LEVEL 6 — Помни редакционния контекст

Добави:

- archive search;
- similar previous articles;
- follow-up dates;
- обещани срокове;
- old vs new source diff;
- recurring topic memory.

Тук системата започва да действа като реален асистент на главния редактор:

> „Преди 6 месеца общината обеща срок до септември. Новото съобщение не споменава този срок.“

Изходът е **предложение за проверка**, не автоматично твърдение.

---

## LEVEL 7 — Авторски стил

Използвай само:

- публикувани;
- редакторски одобрени;
- достатъчно на брой материали.

Първа версия:

```text
retrieved examples
+ compact author style profile
+ source facts
→ draft
```

Не започвай с LoRA или fine-tuning.

За всеки автор пази отделно:

- типична дължина;
- структура;
- lead style;
- употреба на цитати;
- заглавия;
- предпочитана терминология;
- какво да се избягва.

### Gate

Blind comparison:

```text
generic draft
vs
style-assisted draft
```

Редакторът избира без да знае кой вариант е кой.

---

## LEVEL 8 — Рутинни операции

Едва след доказана стабилност могат да се автоматизират операции като:

- nightly health-check;
- broken-link detection;
- parser-canary;
- scheduled already-approved content;
- archive resurfacing queue;
- event reminders;
- internal maintenance alerts.

AI-generated editorial content остава draft-first.

---

# 7. Първи реални автоматизации

Не стартирай всички едновременно.

Препоръчителен ред:

### A. Editorial Telegram Radar

Първо read-only.

### B. Press inbox triage

```text
press@ / signals@
→ extract
→ classify
→ short internal summary
→ Telegram/editor queue
```

Първо без WordPress.

### C. Weather draft

Официален source → structured fields → deterministic template → optional headline AI → WordPress draft.

### D. Post-publication social helper

Published article → Facebook / Telegram / meta variants.

### E. Weekend agenda

Approved events → Friday compilation.

---

# 8. Предложени Skills

Ако harness-ът поддържа reusable skills, създай ги като отделни файлове.

Пример:

```text
.ai/
  skills/
    project-bootstrap.md
    source-adapter.md
    editorial-triage.md
    safe-draft.md
    wordpress-draft.md
    verification-gate.md
```

---

## Skill: `project-bootstrap`

### Purpose

Създава минималната, проверима основа на чисто нов repository, без да добавя редакционни capabilities.

### Must do

- потвърди, че repository е празно или съдържа само начални файлове;
- създаде минимална директория и package структура;
- добави `.gitignore` и `.env.example`;
- добави локален config loader без реални secrets;
- добави structured logging skeleton;
- добави test runner и един smoke test;
- добави `BACKLOG.md` и current milestone файл;
- запази `AUTO_PUBLISH=false`;
- осигури dry-run като default за бъдещи external writes.

### Must not do

- да добавя WordPress integration;
- да добавя Telegram integration;
- да добавя database server;
- да добавя n8n;
- да добавя scraper;
- да добавя LLM provider;
- да изгражда business logic;
- да прави premature abstraction.

---

## Skill: `source-adapter`

### Purpose

Добавя **един** source към ingestion.

### Required contract

```yaml
source_id:
source_url:
fetch_method:
update_frequency:
parser:
normalizer:
dedupe_key:
failure_behavior:
fixtures:
tests:
```

### Required tests

- valid response;
- empty response;
- changed content;
- duplicate;
- timeout;
- malformed HTML/XML.

---

## Skill: `editorial-triage`

Input:

```text
normalized source item
```

Output:

```json
{
  "type": "",
  "priority": "",
  "risk": "",
  "region": [],
  "reason": "",
  "recommended_action": ""
}
```

Не генерира article body.

---

## Skill: `safe-draft`

Работи само върху allow-listed content.

Rules:

1. фактите идват само от source package;
2. всяко число трябва да е traceable;
3. всяко име трябва да е traceable;
4. quote може да се използва само ако присъства verbatim;
5. uncertain data не се „поправя“;
6. output винаги е draft.

---

## Skill: `wordpress-draft`

Позволени операции:

```text
create_draft
update_own_draft
attach_metadata
```

Забранени по default:

```text
publish
delete_published
modify_published
change_homepage
change_category_structure
```

---

## Skill: `verification-gate`

Стартира след всяка capability промяна.

Проверява:

- tests green;
- fixtures;
- duplicate behavior;
- failure behavior;
- secrets;
- production side effects;
- forbidden publish paths;
- audit log.

---

# 9. Предложени Hooks

Hook синтаксисът зависи от конкретния AI harness. Следните са **логически hooks**, които трябва да бъдат mapped към наличната система.

---

## `pre_task`

Преди код:

- прочети този файл;
- прочети current milestone;
- прочети `BACKLOG.md`;
- потвърди scope;
- забрани scope creep.

---

## `pre_external_write`

Преди WordPress/Telegram/email write:

Провери:

```text
dry_run?
allowed_action?
approved_destination?
risk_class?
auto_publish?
```

Ако действието е publish и няма explicit approval:

```text
BLOCK
```

---

## `post_fetch`

Запази:

- source;
- URL;
- fetched_at;
- HTTP status;
- content hash;
- raw snapshot reference.

Това позволява по-късна проверка.

---

## `post_llm`

След AI transform:

Изпълни validator за:

- unsupported numbers;
- unknown names;
- invented quotes;
- missing source URL;
- empty output;
- forbidden risk class.

---

## `post_change`

Автоматично:

- unit tests;
- lint;
- type checks, ако проектът ги използва;
- targeted integration test.

---

## `pre_commit`

Провери:

- accidental secrets;
- unrelated file changes;
- generated junk;
- test result;
- forbidden publish code;
- scope lock.

---

## `post_task`

Генерирай result report и **спри изпълнението**.

---

# 10. Evaluation

Не използвай усещането „изглежда добре“.

За всеки workflow пази малък evaluation set от реални случаи.

---

## Radar metrics

```text
duplicate_rate
false_alert_rate
missed_update_rate
median_detection_latency
parser_failure_rate
editor_open/use_rate
```

---

## Draft metrics

```text
fabricated_fact_rate
unsupported_number_rate
unsupported_quote_rate
editor_acceptance_rate
mean_edit_distance
minutes_saved_per_item
```

---

## Operational metrics

```text
workflow_success_rate
failure_recovery_rate
notification_delay
source_staleness
unexpected_side_effects
```

---

# 11. Progression gate

Ново ниво може да започне само ако:

```text
1. current capability works end-to-end
2. tests pass
3. manual verification passes
4. failure mode is understood
5. rollback exists
6. editor confirms usefulness
7. no unresolved high-risk bug exists
```

Ако редакторът каже:

> „Това ми създава повече работа.“

не добавяй AI.

Поправи или премахни workflow-а.

---

# 12. Backlog — не за V1

Не имплементирай в ранните фази без ново решение:

- LoRA;
- fine-tuning;
- generic NER platform;
- large entity gazetteer;
- CRM;
- pgvector само защото „може“;
- enterprise social listening;
- autonomous hard-news writing;
- scraping на затворени Facebook групи;
- complicated confidence scoring;
- 80-source Playwright farm;
- heavy multi-agent newsroom architecture.

---

# 13. Бързи полезни идеи за по-късно

След стабилизиране на основата:

### Source diff assistant

Показва какво е променено в официална публикация след първата версия.

### Promise / deadline memory

Пази:

```text
who
promised what
date
deadline
source
```

и предлага follow-up.

### Parser canary

Ако source връща HTTP 200, но внезапно 0 items:

```text
ALERT
```

Това често е по-опасно от HTTP 500.

### Archive capsule

На същата дата:

```text
1 year ago
5 years ago
10 years ago
```

предлага подходящ стар материал.

### Storm mode

При официален warning:

- увеличава monitoring frequency;
- приоритизира аварии/транспорт/време;
- намалява cultural noise в редакционния Radar.

Публични промени по homepage се правят само след отделно одобрение.

---

# 14. Definition of Done за всяка малка задача

Задачата **не е завършена**, ако има само код.

Done означава:

```text
[ ] конкретният scope е изпълнен
[ ] няма unrelated refactor
[ ] тестовете минават
[ ] има fixture / reproducible input
[ ] има manual end-to-end proof
[ ] failure case е тестван
[ ] production side effects са описани
[ ] rollback е описан
[ ] документацията е обновена
[ ] предложена е само една следваща малка стъпка
[ ] harness-ът е спрял и чака review
```

---

# 15. Първи задачи при празно repository

Repository започва **от нулата**. Затова няма discovery milestone върху съществуваща архитектура.

Не започвай директно с Radar, Telegram, WordPress, n8n или LLM.

## `M0 — Project Bootstrap + Safety Foundation`

Целта на M0 е да създаде само минималната основа, върху която следващите малки capabilities могат да бъдат тествани независимо.

### M0 scope

Harness-ът трябва само да:

1. създаде минимална project/package структура;
2. добави `.gitignore`;
3. добави `.env.example`, без реални credentials;
4. добави config loader;
5. добави structured logging skeleton;
6. добави `AUTO_PUBLISH=false` като hard default;
7. добави `DRY_RUN=true` като hard default за бъдещи external writes;
8. добави test runner и един smoke test;
9. добави `BACKLOG.md`;
10. добави current milestone/status файл;
11. добави `.ai/skills/` и началните harness skill файлове;
12. изпълни тестовете и покаже доказателство, че clean checkout може да стартира локално.

### Предпочитан минимален skeleton

```text
.
├── README.md
├── AI_HARNESS_EDITOR_ASSISTANT.md
├── BACKLOG.md
├── MILESTONE.md
├── .gitignore
├── .env.example
├── pyproject.toml
├── src/
│   └── editor_assistant/
│       ├── __init__.py
│       ├── config.py
│       └── logging_setup.py
├── tests/
│   └── test_smoke.py
├── fixtures/
└── .ai/
    └── skills/
        ├── project-bootstrap.md
        ├── source-adapter.md
        └── verification-gate.md
```

Това е ориентир, не причина за framework redesign. Ако harness-ът има добра причина за по-малък skeleton, предпочети по-малкия.

### Забранено в M0

- WordPress API calls;
- Telegram API calls;
- n8n deployment;
- PostgreSQL/Qdrant/Redis;
- scraper/browser automation;
- LLM API calls;
- source-specific parser;
- editorial classification;
- article generation;
- production side effects;
- generic plugin architecture;
- dependency-heavy framework.

### M0 acceptance criteria

```text
[ ] Clean checkout може да инсталира проекта.
[ ] Test runner стартира успешно.
[ ] Smoke test минава.
[ ] Config се зарежда без production credentials.
[ ] AUTO_PUBLISH е false по default.
[ ] DRY_RUN е true по default.
[ ] Няма network call при tests.
[ ] Няма external write path.
[ ] Няма secret в repository.
[ ] Logging skeleton може да запише structured local log.
```

### M0 output

```markdown
# M0 Bootstrap Report

## Created
## Dependencies added
## Tests run
## Test result
## Config defaults
## External side effects
## Security checks
## Known limitations
## Rollback
## Recommended next smallest step
```

След M0:

> **STOP AND WAIT FOR REVIEW**

---

## Следващите milestones също се раздробяват

Не скачай от M0 директно към пълен `One Source → Telegram` workflow.

### `M1.1 — Source Contract + Fixture Only`

Само:

```text
fixture
→ parser
→ normalized object
→ local test output
```

Без network. Без Telegram. Без persistence.

Проверяваме schema, parser contract и failure behavior.

### `M1.2 — One Real Source, Read-Only`

Само:

```text
1 real public source
→ fetch
→ parser
→ normalized object
→ console/local JSON
```

Без Telegram и без database.

Проверяваме реалния HTML/RSS/API и устойчивостта на parser-а.

### `M1.3 — Local State + Dedupe`

Добавя се най-малкият достатъчен persistent state, например SQLite, само ако е необходим.

```text
source item
→ normalize
→ content identity/hash
→ local state
→ NEW / UNCHANGED / UPDATED
```

Проверяваме duplicate и update behavior.

### `M1.4 — Telegram Test Channel`

Едва след доказани M1.1–M1.3:

```text
1 source
→ fetch
→ normalize
→ dedupe
→ Telegram TEST channel
```

Само test destination. Никакъв production editorial channel.

След всеки milestone:

> **STOP AND WAIT FOR REVIEW**

---

# 16. Финално правило

Оптимизираме не за:

> „Колко много може AI?“

а за:

> **„Колко редакторско време спестяваме, без да увеличаваме риска?“**

Всеки capability трябва да доказва това преди следващото надграждане.
