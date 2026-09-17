# M2.2 Human Review - Frozen Style System (editor decision artifact, v m2.2-freeze-1)

Corpus: 150 articles (sha256_canonical `d32629ae7e9d3b726a0264056a37c7fa550dfbf6272cf25d34cc51718bfdbcba`), 2009-08-02 to 2026-09-11. House 83 / Desislava 59 / unknown 8.
Frozen architecture: SITE DNA + VOICE + STORY MODE. Voices and modes compose (e.g. DESISLAVA + CULTURE_FEATURE); no AUTHOR_X_NEWS x MODE explosion.
Style language rule: profiles use often / typically / prefer / common-pattern / avoid-unless-source-supports. Observed tendencies, not mechanical grammar.

## Site DNA (shared, not a selectable draft style)
- **language**: Bulgarian; direct informative headline (typical 40-60 chars, 7-9 words), no colon / question / exclamation in headlines (0% in 2020-2026 bands).
- **numbers_dates**: Digits in ~26-32% of recent headlines; body number-density ~11-16 per 1000 chars. Bulgarian date forms ('1-ви септември', '16-ти май') and clock forms ('12.30 ч.'). Ordinal '-ти/-ви' style is house-wide, not author-specific.
- **local_specificity**: Every group carries Burgas-region anchors (median 1-3 local-name hits per article); institution naming is formal-full ('Областна дирекция на МВР в Бургас', 'Регионален исторически музей - Бургас', 'Община Камено').
- **quotation**: Quoted speech stays inline in body (structured blockquote count is 0 across all 150); quote-mark density ~5-8 per 1000 chars; attribution verbs (съобщиха, каза, заяви).
- **structure**: No structural lead/subheadline element anywhere in the corpus (subheadline None in 150/150). Caption + tags are CMS-level metadata, not style: caption present ~89-100% everywhere, tags ~2.5-5.6 everywhere - do NOT treat as voice.
- **headline_opening**: Headline states the news fact directly; body normally opens with the same fact expanded (immediate_fact 68-70% overall) - never a delayed literary lede.

## Composition map
- Voices: VOICE_HOUSE, VOICE_DESISLAVA_RECENT
- Modes: MODE_STANDARD_NEWS, MODE_BRIEF, MODE_EVENT_PREVIEW, MODE_CULTURE_FEATURE
- Default M2.3 compositions: Story A HOUSE+STANDARD, Story B HOUSE+BRIEF, Story C HOUSE+EVENT_PREVIEW, Story D HOUSE+CULTURE_FEATURE, Story E DESISLAVA_RECENT+STANDARD (also valid: DESISLAVA+CULTURE, DESISLAVA+EVENT, future AUTHOR_X+any MODE).
- Retrieval order: requested VOICE+MODE -> same MODE other voice -> HOUSE+STANDARD. Never mix unrelated voices to fill context.

---

## VOICE_HOUSE [voice, PROVEN, n=83] - House voice (editorial, unsigned)
Scope: house-signed material 2020-2026 (n=83 core; 40 in 3-5 para shape)
Preferred use: Default unsigned voice for news drafts; combine with any STORY MODE.
Sources: authors=['Черноморие-бг']; categories=['Общество', 'Култура', 'Туризъм', 'Бизнес', 'Спорт', 'Образование']
Headline: Direct fact statement: 'Набират доброволци за разкопките на Русокастро'.; Result/decision form: 'Черноморец взе три точки от Берое'.; Number-led service form: '21 сигнала за мазут по Черноморието...'.; No quote/colon/question marks (0% quotes in house 2020+).
Opening: Immediate fact expanded: P1 restates headline + adds who/when/where in the same sentence.; Institutional attribution in P1: 'съобщават от НИМХ', 'съобщиха от пресцентъра на ОД на МВР'.; Opening classes: immediate_fact ~77% in recent house (37/48); event_date_first ~12%; place_first ~6%.
Body: 3-5 paragraphs; median body ~1000-1330 chars; first para longest (median ~267-455 chars), closing para short (~195-230). Medium sentences, median ~16-17 words; no one-line staccato. Even: fact -> detail -> context -> short closing line.
Quotes: Inline quotes only; quote-mark density ~3-6 per 1000 chars (lower than culture). Quote normally in P2-P4, avoid as the opening line (quote_first 1/48 recent house).
Tone: Typically factual; adjectives only in institutional names. Distant third person; first-person 0-2%.
Numbers/dates: Press-center formula verbatim: 'съобщиха от пресцентъра на Областна дирекция на МВР в Бургас'.; Full dates with ordinal: 'на 1-ви септември около 21.10 ч.'.; Number + unit spelled in body ('км. 442+700', '2-3 бала').
Lexicon: 'съобщиха от пресцентъра', 'е станал/станал', 'в района', 'с бургаска регистрация', 'почистване/разпореди' (service verbs).
Avoid (tendencies, not hard rules): Avoid invent a blockquote or pull-quote layout.; Avoid add a subheadline/lead element (template has none).; Avoid use first person or rhetorical questions.; Avoid treat caption/tags as voice (they are CMS metadata).
Evidence: House 2020-2026 n=83 (recent n=48 + mid n=23 + spill); 3-5 para core n=40; hl_repeat 0%; hl_quote ~0-2%; immediate_fact 37/48 recent-house; quote density ~3-6/1000; number density ~11-16/1000; caption ~93-98%. Voice claims come only from house-signed material, never from an all-author average.

### 5 representative articles (read headline + P1 + last para)

#### 2ba12a8ede485a3c | 2022-10-22 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/20-temperaturi-se-zavrashtat-ot-dnes-5906
headline: 20° температури се завръщат от днес
P1: В повечето райони на страната ще е тихо в съботния ден. На места главно в Горнотракийската низина и котловините ще се образува мъгла или ниска инверсионна облачност, съобщават от Националния институт по метеорология и хидрология. Минималните температури ще са между 1° и 6°, в София около 3°. Утре ще е предимно слънчево. Ще има временни увеличения на облачността, средна и висока, по-значителна в Северна България. Ще духа слаб, в североизточните райони - умерен вятър от юг-югозапад и с него ще се 
LAST: Над Черноморието ще е предимно слънчево. По-значителни временни увеличения на облачността ще има по северното крайбрежие. Ще духа до умерен юг-югозападен вятър. Максималните температури ще са между 16° и 20°. Температурата на морската вода е 16-17°. Вълнението на морето ще е 2-3 бала.
(npara=3, nchar=1144)

#### 4eba4d9c0bf6def9 | 2024-06-21 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/carkvata-pochita-sveti-yulian-tarsiyski-9502
headline: Църквата почита свети Юлиан Тарсийски
P1: Православната църква почита днес свети мъченик Юлиан Тарсийски, свети свещеномъченик Терентий, епископ Иконийски, преподобни Юлий презвитер и Юлиан дякон.
LAST: След като тялото на Юлиан било изхвърлено на брега, благочестива и вярваща вдовица го прибрала и го занесла в Александрия. Там погребала плътта на мъченика с християнски почести.
(npara=5, nchar=1187)

#### 8a1f3693ed7aafd2 | 2024-06-19 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/nabirat-dobrovolci-za-razkopkite-na-rusokastro-4829
headline: Набират доброволци за разкопките на Русокастро
P1: Набират доброволци за разкопките на крепоста "Русокастро". Те ще започнат на 1-ви юли 2024 г. Задачата на археологическият екип е да допроучи северозападната крепостна стена на средновековния град, с прилежащите ѝ кули. Разкопките за поредна година са финансирани от Община Камено и се изпълняват от Регионален исторически музей – Бургас.
LAST: За всякакви въпроси като работно време и други подобни, можете да се обърнете към Красимира Стоянова – археолог в РИМ – Бургас, и член на проучвателския екип, e-mail [email protected] Тел. 0882 70 49 79.
(npara=5, nchar=1745)

#### e467d7a72cd65d2b | 2024-06-20 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/praznikat-na-varna-shte-bade-neprisastven-3815
headline: Празникът на Варна ще бъде неприсъствен
P1: Денят на Варна – 15-ти август, ще бъде празничен и неприсъствен ден. С пълно единодушие съветниците от Постоянна комисия по култура и духовно развитие решиха традицията да бъде спазена и тази година. Решението на комисията ще бъде подложено на гласуване от Общинския съвет на редовното му заседание на 27 юни 2024 г.
LAST: По традиция на 15 август се връчват на заслужили граждани на морския град високите звания и отличия „Почетен гражданин на Варна” и "За заслуги към Варна".
(npara=4, nchar=857)

#### 85ad7db08d7d1bf2 | 2026-09-08 | Черноморие-бг | На път
url: https://chernomorie-bg.com/post/zemni-masi-se-svlyakoha-na-patya-za-brodilovo-shofirayte-vnimatelno-5194
headline: Земни маси се свлякоха на пътя за Бродилово, шофирайте внимателно
P1: Земни маси се свлякоха на пътя за царевското село Бродилово. Заради това се въвежда временна организация на движението в засегнатия участък, съобщиха от Община Царево.
LAST: Временната организация ще остане в сила до приключване на необходимите дейности и възстановяване на нормалното и безопасно движение.
(npara=4, nchar=581)

### 2 contrasting articles (NOT this voice/mode)
- 2ba12a8ede485a3c | 2022-10-22 | Черноморие-бг | Общество | headline: 20° температури се завръщат от днес | url: https://chernomorie-bg.com/post/20-temperaturi-se-zavrashtat-ot-dnes-5906
- eb3262c0b6935eb6 | 2009-08-02 | Десислава Георгиева | Култура | headline: Екипът на “Летя” спечели 20 бона на “Бургас и морето” | url: https://chernomorie-bg.com/post/-20-

### Editor verdict
- KEEP / MERGE(->which?) / DROP + one-line reason
---

## VOICE_DESISLAVA_RECENT [voice, PROVISIONAL, n=12] - Desislava Georgieva, recent signed voice (2024-2026)
Scope: author Десислава Георгиева, 2024-2026 only (12 articles)
Preferred use: Opt-in signed voice for reportage-style drafts; combine with a STORY MODE (often STANDARD or CULTURE).
Sources: authors=['Десислава Георгиева']; categories=['Култура', 'Туризъм', 'Общество', 'Образование']
Headline: Ceremony/forum result: 'В Царево раздадоха годишните награди за туризъм'.; Institutional meeting: 'НХА и държавният ВУЗ с меморандум...'.; Video tag form: '... - видео'.
Opening: On-scene opening with place + occasion: 'В Царево раздадоха... Морската община стана домакин...'.; Second voice early: P2 already carries a named quote.; immediate_fact 9/12; place_first 2/12.
Body: 5-6 paras median (5.5), median body ~1640 chars (longest of recent groups). Median ~15.6 words; quote paragraphs alternate with narrative. Scene -> voice -> voice -> detail -> result-list closing.
Quotes: Quote density ~6.0/1000 with multiple distinct speakers per article (vs single-source house). Quotes from P2 onward, several speakers.
Tone: Factual with on-scene color ('Морската община стана домакин', 'в първия ден на лятото'). Closest to the scene; still third person.
Numbers/dates: Motto lines kept ('Мотото на наградите тази година е: ...').; Role + full name on every quote.; Result/category lists in closing.
Lexicon: 'домакин', 'церемония', 'форум/семинар', 'мотото', 'връчване на отличията/наградите', 'категории'.
Avoid (tendencies, not hard rules): Avoid publish under a house signature (requires named byline).; Avoid reduce to a single source.; Avoid use blotter compression.; Do not generalize beyond 2024-2026: legacy Desislava (pre-2020) wrote differently (headline-repeat 64%, quoted headlines 24%) and is NOT part of this profile.
Evidence: Recent Desislava n=12 vs recent house n=48 (same band): body ~1644 vs ~1111ch; paras 5.5 vs 4.5; hl ~60 vs ~52ch; tags ~7.3 vs ~4.4; several named voices per article vs single-source house. Legacy pre-2020 Desislava (headline-repeat 64%, quoted headlines 24%, CMS-era) is documented drift and explicitly excluded from this scope.

### 5 representative articles (read headline + P1 + last para)

#### 70af89955d6c6678 | 2026-07-07 | Десислава Георгиева | Туризъм
url: https://chernomorie-bg.com/post/32-metrovo-viensko-kolelo-shte-se-varti-pred-panteona-v-burgas-video-3576
headline: 32-метрово виенско колело ще се върти пред Пантеона в Бургас - видео
P1: 32-метрово виенско колело ще се върти на алеята пред Пантеона в Морската градина на Бургас. Огромното съоръжение вече се монтира със специален кран, който вдига тежести по няколко тона. Районът, където се извършват монтажните дейности, е отцепен с ограничителни ленти. За да стигнат до плажа, местни и гости заобикалят и минават почти през тревните площи. Съоръжението трябва да бъде сглобено до дни и да заработи. По информация от Община Бургас виенското колело ще остане като атракцион на това мяст
LAST: Интересен е фактът, че съоръжението се монтира на броени метри от лунапарка, който е постоянен атракцион, изграден до Стената на приказките и привлича деца на различна възраст.
(npara=4, nchar=1182)

#### c4cb10ba043547be | 2024-06-19 | Десислава Георгиева | Култура
url: https://chernomorie-bg.com/post/mecenatat-rusi-kurtlakov-finansira-plastika-na-car-ivan-aleksandar-7025
headline: Меценатът Руси Куртлаков финансира пластика на цар Иван Александър
P1: Бургаският бизнесмен и меценат Руси Куртлаков заедно с други дарители ще финансират изработването на пластика на цар Иван Александър. Тя ще бъде изработена от врачански варовик, който тежи 8 тона и е осигурен от Куртлаков. Монументалната пластика на цар Иван Александър ще бъде висока 3 метра. Тя ще бъде изработена от художниците Даниел Кънчев и Атанас Стоянов. Те започват работа на 1-ви юли в базата на Руси Куртлаков, която се намира в Камено.
LAST: Сред инициаторите за изработването на пластиката, освен Руси Куртлаков, са и областният управител на област Бургас Мария Нейкова, кметът на Община Камено Жельо Вардунски, директорът на Регионалния исторически музей в Бургас д-р Милен Николов, който ръководи разкопките на Русокастро.
(npara=3, nchar=996)

#### c50b58ea43089f96 | 2024-06-17 | Десислава Георгиева | Общество
url: https://chernomorie-bg.com/post/prenasyat-opita-na-carkvata-v-darjavnite-socialni-uslugi-v-burgas-3281
headline: Пренасят опита на Църквата в държавните социални услуги в Бургас
P1: Опитът на Софийска епархия в държавните социални услуги бе представен в Бургас в рамките на семинара "Социална свързаност и подкрепа", който се провежда на 17-ти и 18-ти юни в гранд хотел и СПА "Приморец" в Бургас. Форумът се организира в рамките на проект, финансиран от фонд "Социална закрила" към Министерството на труда и социалната политика и се изпълнява от сдружение "Света Богородица", първият доставчик на социални услуги към църквата.
LAST: В рамките на форума ще бъдат поставени важни теми, свързани с регистрацията на НПО, лицензиране за предоставяне на социални услуги и други, като участие ще вземат също и изпълнителният директор на Агенция за качество на социалните услуги – Виктория Тахова и председателят на Държавна агенция за закри
(npara=7, nchar=2534)

#### de1feb5a5c626507 | 2026-07-20 | Десислава Георгиева | Култура
url: https://chernomorie-bg.com/post/romantichna-istoriya-ot-60-te-otkriva-burgaskiya-filmov-festival-5106
headline: Романтична история от 60-те открива бургаския филмов фестивал
P1: Романтична история от края на 60-те години на миналия век открива тази вечер 11-то издание на "Burgas International Film Festival" (BIFF). Документалният филм "Снежа и Франц" на режисьора Светослав Драганов ще бъде показан на открита сцена Охлюва от 21.30 часа. С тази прожекция ще бъде сложено началото на тазгодишното издание на фестивала, който за първи път започва в понеделник и ще приключи в събота.
LAST: Събитието се организира от фондация "Модерат" с финансовата подкрепа на Община Бургас и медийното партньорство на сайт "Черноморие-бг".
(npara=10, nchar=2396)

#### 587c9679e21f2c04 | 2024-06-21 | Десислава Георгиева | Туризъм
url: https://chernomorie-bg.com/post/v-carevo-razdadoha-godishnite-nagradi-za-turizam-9962
headline: В Царево раздадоха годишните награди за туризъм
P1: В Царево раздадоха годишните награди за туризъм. Морската община стана домакин на шестата церемония по връчване на отличията. "За първи път наградите се връчват извън столицата и то по покана на кмета на Царево Марин Киров. Затова в първия ден на лятото Царево става столица на туризма", каза организаторът на годишните награди – Борислав Ангелов. Те се присъждат в партньорство с Министерството на туризма, а победителите в отделните категории се определят от международно жури от експерти от Българ
LAST: В категория "Градски хотел" отличието спечели "Хилтън". В категорията "Зелен СПА хотел" - "Санте" - Велинград, в категорията "Крайбрежен хотел" - "The Lodge" в Царево, а в категорията "Хотелска верига" - "Hyatt".
(npara=6, nchar=1872)

### 2 contrasting articles (NOT this voice/mode)
- 1ad2de3ce83318fd | 2025-04-30 | Черноморие-бг | На път | headline: Блъснаха украинка с велосипед | url: https://chernomorie-bg.com/post/blasnaha-ukrainka-s-velosiped-1421
- eb3262c0b6935eb6 | 2009-08-02 | Десислава Георгиева | Култура | headline: Екипът на “Летя” спечели 20 бона на “Бургас и морето” | url: https://chernomorie-bg.com/post/-20-

### Editor verdict
- KEEP / MERGE(->which?) / DROP + one-line reason
---

## MODE_STANDARD_NEWS [story_mode, PROVEN, n=40] - Standard news (3-5 paras)
Scope: house-signed 2020-2026, 3-5 paras (n=40); voice-neutral shape
Preferred use: Default news shape; combine with VOICE_HOUSE normally, or with VOICE_DESISLAVA_RECENT for a signed standard report.
Sources: authors=['Черноморие-бг']; categories=['Общество', 'Култура', 'Туризъм', 'Бизнес', 'Спорт', 'Образование']
Headline: Direct fact statement: 'Набират доброволци за разкопките на Русокастро'.; Result/decision form: 'Черноморец взе три точки от Берое'.; Number-led service form: '21 сигнала за мазут по Черноморието...'.; No quote/colon/question marks (0% quotes in house 2020+).
Opening: Immediate fact expanded: P1 restates headline + adds who/when/where in the same sentence.; Institutional attribution in P1: 'съобщават от НИМХ', 'съобщиха от пресцентъра на ОД на МВР'.; Opening classes: immediate_fact ~77% in recent house (37/48); event_date_first ~12%; place_first ~6%.
Body: 3-5 paragraphs; median body ~1000-1330 chars; first para longest (median ~267-455 chars), closing para short (~195-230). Medium sentences, median ~16-17 words; no one-line staccato. Even: fact -> detail -> context -> short closing line.
Quotes: Inline quotes only; quote-mark density ~3-6 per 1000 chars (lower than culture). Quote normally in P2-P4, avoid as the opening line (quote_first 1/48 recent house).
Tone: Typically factual; adjectives only in institutional names. Distant third person; first-person 0-2%.
Numbers/dates: Press-center formula verbatim: 'съобщиха от пресцентъра на Областна дирекция на МВР в Бургас'.; Full dates with ordinal: 'на 1-ви септември около 21.10 ч.'.; Number + unit spelled in body ('км. 442+700', '2-3 бала').
Lexicon: 'съобщиха от пресцентъра', 'е станал/станал', 'в района', 'с бургаска регистрация', 'почистване/разпореди' (service verbs).
Avoid (tendencies, not hard rules): Avoid invent a blockquote or pull-quote layout.; Avoid add a subheadline/lead element (template has none).; Avoid use first person or rhetorical questions.; Avoid treat caption/tags as voice (they are CMS metadata).
Evidence: House 2020-2026 3-5 para core n=40; body ~1000-1330ch; sent ~16-17w; hl ~52-56ch/8-9w; hl_repeat 0%; hl_quote ~0%; quote density ~3-6/1000.

### 5 representative articles (read headline + P1 + last para)

#### 2ba12a8ede485a3c | 2022-10-22 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/20-temperaturi-se-zavrashtat-ot-dnes-5906
headline: 20° температури се завръщат от днес
P1: В повечето райони на страната ще е тихо в съботния ден. На места главно в Горнотракийската низина и котловините ще се образува мъгла или ниска инверсионна облачност, съобщават от Националния институт по метеорология и хидрология. Минималните температури ще са между 1° и 6°, в София около 3°. Утре ще е предимно слънчево. Ще има временни увеличения на облачността, средна и висока, по-значителна в Северна България. Ще духа слаб, в североизточните райони - умерен вятър от юг-югозапад и с него ще се 
LAST: Над Черноморието ще е предимно слънчево. По-значителни временни увеличения на облачността ще има по северното крайбрежие. Ще духа до умерен юг-югозападен вятър. Максималните температури ще са между 16° и 20°. Температурата на морската вода е 16-17°. Вълнението на морето ще е 2-3 бала.
(npara=3, nchar=1144)

#### 4eba4d9c0bf6def9 | 2024-06-21 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/carkvata-pochita-sveti-yulian-tarsiyski-9502
headline: Църквата почита свети Юлиан Тарсийски
P1: Православната църква почита днес свети мъченик Юлиан Тарсийски, свети свещеномъченик Терентий, епископ Иконийски, преподобни Юлий презвитер и Юлиан дякон.
LAST: След като тялото на Юлиан било изхвърлено на брега, благочестива и вярваща вдовица го прибрала и го занесла в Александрия. Там погребала плътта на мъченика с християнски почести.
(npara=5, nchar=1187)

#### 8a1f3693ed7aafd2 | 2024-06-19 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/nabirat-dobrovolci-za-razkopkite-na-rusokastro-4829
headline: Набират доброволци за разкопките на Русокастро
P1: Набират доброволци за разкопките на крепоста "Русокастро". Те ще започнат на 1-ви юли 2024 г. Задачата на археологическият екип е да допроучи северозападната крепостна стена на средновековния град, с прилежащите ѝ кули. Разкопките за поредна година са финансирани от Община Камено и се изпълняват от Регионален исторически музей – Бургас.
LAST: За всякакви въпроси като работно време и други подобни, можете да се обърнете към Красимира Стоянова – археолог в РИМ – Бургас, и член на проучвателския екип, e-mail [email protected] Тел. 0882 70 49 79.
(npara=5, nchar=1745)

#### e467d7a72cd65d2b | 2024-06-20 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/praznikat-na-varna-shte-bade-neprisastven-3815
headline: Празникът на Варна ще бъде неприсъствен
P1: Денят на Варна – 15-ти август, ще бъде празничен и неприсъствен ден. С пълно единодушие съветниците от Постоянна комисия по култура и духовно развитие решиха традицията да бъде спазена и тази година. Решението на комисията ще бъде подложено на гласуване от Общинския съвет на редовното му заседание на 27 юни 2024 г.
LAST: По традиция на 15 август се връчват на заслужили граждани на морския град високите звания и отличия „Почетен гражданин на Варна” и "За заслуги към Варна".
(npara=4, nchar=857)

#### 85ad7db08d7d1bf2 | 2026-09-08 | Черноморие-бг | На път
url: https://chernomorie-bg.com/post/zemni-masi-se-svlyakoha-na-patya-za-brodilovo-shofirayte-vnimatelno-5194
headline: Земни маси се свлякоха на пътя за Бродилово, шофирайте внимателно
P1: Земни маси се свлякоха на пътя за царевското село Бродилово. Заради това се въвежда временна организация на движението в засегнатия участък, съобщиха от Община Царево.
LAST: Временната организация ще остане в сила до приключване на необходимите дейности и възстановяване на нормалното и безопасно движение.
(npara=4, nchar=581)

### 2 contrasting articles (NOT this voice/mode)
- 2ba12a8ede485a3c | 2022-10-22 | Черноморие-бг | Общество | headline: 20° температури се завръщат от днес | url: https://chernomorie-bg.com/post/20-temperaturi-se-zavrashtat-ot-dnes-5906
- 34d9f530ecf1f9fb | 2016-07-06 | ? | На път | headline: Затварят за час утре улица Преслав във Варна | url: https://chernomorie-bg.com/post/zatvarjat-za-cas-utre-ulica-preslav-vav-varna

### Editor verdict
- KEEP / MERGE(->which?) / DROP + one-line reason
---

## MODE_BRIEF [story_mode, PROVISIONAL, n=15] - Brief (1-2 paras, blotter/service)
Scope: house-signed 2020-2026, 1-2 paras (n=15); voice-neutral shape
Preferred use: Short single-fact items: incident blotter, send-off notices. Editor command: write it short, do not inflate.
Sources: authors=['Черноморие-бг']; categories=['На път', 'Общество', 'Образование']
Headline: Incident result form: 'Мъж се блъсна в комбайн и загина на място'.; School send-off form: 'Морското изпраща 70 абитуриента'.; Number/alcohol form: 'Моторист шофирал с 2.21 промила алкохол'.; No quotes/colons/questions in headlines.
Opening: Whole story in one block (median 558 chars, 1 para): headline fact + ', съобщиха от пресцентъра...' + time/place/vehicle details.; No development arc: the first sentence IS the story.
Body: 1-2 paragraphs, median ~558 chars; first para median ~558 (whole story). Shorter sentences, median ~13 words; dense with numbers. Flat: all facts at once, no build.
Quotes: Few or no quotes; quote density ~7.7/1000 comes from quoted vehicle/place names, not speech. Attribution in sentence 1.
Tone: Typically concise blotter-factual. Usually distant; first-person 0%.
Numbers/dates: Among the highest number densities observed of any profile (~16.8/1000): times, ages, registration, promille.; Ordinal date + clock in sentence 2, typically.
Lexicon: 'съобщиха от пресцентъра', 'Инцидентът е станал/станал', 'с бургаска регистрация', 'управляван от ...-годишен', 'движещ се с несъобразена скорост'.
Avoid (tendencies, not hard rules): Avoid pad to 4-5 paragraphs.; Avoid add scene-setting or quotes.; Avoid soften into feature tone.
Evidence: House 2020-2026 briefs n=15 (11 in 2024-2026); body med ~558ch; 1-2 paras; sentences ~13w; number density ~16.8/1000 (highest observed); shortest headlines (~39ch). Provisional only on sample size, but internally consistent and recent.

### 5 representative articles (read headline + P1 + last para)

#### 1ad2de3ce83318fd | 2025-04-30 | Черноморие-бг | На път
url: https://chernomorie-bg.com/post/blasnaha-ukrainka-s-velosiped-1421
headline: Блъснаха украинка с велосипед
P1: Блъснаха украинка с велосипед,, съобщиха от пресцентъра на Областна дирекция на МВР в Бургас. Инцидентът е станал на 29-ти април около 12.30 ч. в района пред хотел "Нимфа" в Слънчев бряг. Лек автомобил "Фолксваген Голф", с бургаска регистрация, управляван от 74-годишен бургазлия, при движение на заден ход блъска премнаващата зад автомобила 38-годишна велосипедиска - украинска гражданка. От удара жената е получила фрактура на лявата ръка.
LAST: Блъснаха украинка с велосипед,, съобщиха от пресцентъра на Областна дирекция на МВР в Бургас. Инцидентът е станал на 29-ти април около 12.30 ч. в района пред хотел "Нимфа" в Слънчев бряг. Лек автомобил "Фолксваген Голф", с бургаска регистрация, управляван от 74-годишен бургазлия, при движение на зад
(npara=1, nchar=441)

#### 8895ec13c20a424f | 2023-08-30 | Черноморие-бг | На път
url: https://chernomorie-bg.com/post/kola-se-zabi-v-spirasht-kamion-jena-s-opasnot-za-jivota-5167
headline: Кола се заби в спиращ камион, жена с опаснот за живота
P1: Кола се заби в спиращ камион, жена с опаснот за живота, съобщиха от пресцентъра на Областна дирекция на МВР в Бургас. Катастрофата е станала на 29-ти август около 17.11 ч. на автомагистрала "Тракия", км. 356 в посока Бургас. Лек автомобил "Фолксваген Пасат", с бургаска регистрация, управляван от 43-годишен бургазлия, поради движение с несъобразена скорост блъска отзад движещия се и спиращ в колоната товарен автомобил "Скания" с прикачено полуремарке, с бургаска регистрация, управляван от 43-годи
LAST: Кола се заби в спиращ камион, жена с опаснот за живота, съобщиха от пресцентъра на Областна дирекция на МВР в Бургас. Катастрофата е станала на 29-ти август около 17.11 ч. на автомагистрала "Тракия", км. 356 в посока Бургас. Лек автомобил "Фолксваген Пасат", с бургаска регистрация, управляван от 43-
(npara=1, nchar=870)

#### c5bc868932a3d50a | 2025-05-15 | Черноморие-бг | Образование
url: https://chernomorie-bg.com/post/morskoto-izprashta-70-abiturienti-7672
headline: Морското изпраща 70 абитуриента
P1: Бургаската Професионална гимназия по морско корабоплаване и риболов "Свети Никола", известна още като Морското училище, изпраща на 16-ти май абитуриентите от "Випуск'2025". Тази година завършват 70 абитуриенти, които се обучаваха през последните пет години в специалностите - "Корабоводене", "Корабни машини и механизация" и "Митническа и данъчна декларация".
LAST: Директорът на гимназията Христина Жабова ще приветства дванайсетокласниците и ще им пожелае попътен вятър в живота!
(npara=2, nchar=476)

#### 6b11bb7e27ec2fde | 2025-05-16 | Черноморие-бг | Образование
url: https://chernomorie-bg.com/post/s-cherven-kilim-izpratiha-vipusk2025-na-burgaskoto-su-sv-sv-kiril-i-metodiy-6626
headline: С червен килим изпратиха Випуск'2025 на бургаското СУ Св. св. Кирил и Методий
P1: С червен килим изпратиха "Випуск'2025" на бургаското СУ "Св. св. Кирил и Методий". 16-ти май бе последният учебен ден за 78-те момичета и момчета, които завършват едно от най-старите училища в морския град. Под звуците на училищния звънец и с отброяване от 1 до 12 абитуриентите се събраха в дрора на школото, за да бъдат изпратени с тържествена церемония. Те бяха приветствани с аплодисменти от своите родители, от учениците от гимназията и от учителите си. Зрелостниците бяха поздравени от директор
LAST: Мажоретният състав на училището зарадва за пореден път с изпълненията си учениците. А зрелостниците, след като минаха по червения килим, се събраха за обща снимка на стълбите на едноименния площад до гимназията.
(npara=2, nchar=824)

#### f0fde7667ae539c4 | 2026-09-11 | Черноморие-бг | Общество
url: https://chernomorie-bg.com/post/zapechataha-pet-nezakonni-sgradi-v-baba-alino-2083
headline: Запечатаха пет незаконни сгради в Баба Алино
P1: Забраниха достъпа до пет незаконни строежа в местността Баба Алино. Днес на терен служители на Община Варна запечатаха сградите. Действията са извършени съгласно заповед по чл. 224 а от Закона за устройство на територията (ЗУТ), издадена от кмета на Община Варна Благомир Коцев още на 1-ви септември 2026 г. При извършените неколкократни проверки от служители на Община Варна и на Общинска полиция, е констатирано, че в сградите не живеят хора.
LAST: Община Варна и Общинска полиция ще осъществяват текущ контрол да не се нарушава забраната.
(npara=2, nchar=536)

### 2 contrasting articles (NOT this voice/mode)
- 1ad2de3ce83318fd | 2025-04-30 | Черноморие-бг | На път | headline: Блъснаха украинка с велосипед | url: https://chernomorie-bg.com/post/blasnaha-ukrainka-s-velosiped-1421
- eb3262c0b6935eb6 | 2009-08-02 | Десислава Георгиева | Култура | headline: Екипът на “Летя” спечели 20 бона на “Бургас и морето” | url: https://chernomorie-bg.com/post/-20-

### Editor verdict
- KEEP / MERGE(->which?) / DROP + one-line reason
---

## MODE_EVENT_PREVIEW [story_mode, PROVEN, n=21] - Event preview / announcement
Scope: future/event-marker articles 2024-2026, 3-8 paras (n=21); cross-author
Preferred use: Forward-looking drafts: festival/concert/exhibition announcements with program + practical info.
Sources: authors=['Черноморие-бг', 'Десислава Георгиева']; categories=['Култура', 'Туризъм', 'Образование', 'Общество']
Headline: Future announcement: 'Епопея на забравените с премиера през септември...'.; Program form: 'Варненско лято продължава със симпозиум, конференция и форум...'.; Edition + date: 'Деветото издание ... започва на 7 октомври'.
Opening: Future-tense P1: 'ще има своята премиера на 18-ти септември на сцената...'.; Date/venue early: day + month + stage/town inside the first 2 sentences.; 'ще' density ~2.2/1000 vs ~0.7 in non-event articles.
Body: 5 paras median (vs 4 non-event); median body ~1580 chars (vs ~1120). Long sentences, median ~17.1 words (vs ~15.4). Announcement -> program -> participants -> practical info (dates/tickets/venue).
Quotes: Quote density ~7.4/1000 (titles + organizer speech). Organizer quote in P2-P3.
Tone: Factual but anticipatory; mild promotional adjectives allowed ('емблематичният', 'зрелищно'). Third person; first-person 0%.
Numbers/dates: Future tense + exact date ('ще има своята премиера на 18-ти септември').; Program enumeration with names.; Practical closing (start/venue/support).
Lexicon: 'ще', 'предстои', 'ще се проведе/състои', 'програма', 'премиера', 'издание', 'фестивал/концерт/изложба', 'започва на'.
Avoid (tendencies, not hard rules): Avoid write the event as already happened.; Avoid omit when/where.; Avoid use blotter style.
Evidence: Event-marker n=21 vs non-event n=104: ще-density ~2.2 vs ~0.7/1000; body ~1580 vs ~1120ch; sentences ~17.1 vs ~15.4w. Kept separate from CULTURE_FEATURE: announcement task (what is coming, when/where) vs report task (what happened, acts/prizes/context). Retrieval prefers this mode when the request is forward-looking.

### 5 representative articles (read headline + P1 + last para)

#### 11ca6a679e85e3b8 | 2025-08-19 | Черноморие-бг | Култура
url: https://chernomorie-bg.com/post/emblematichniyat-orlin-goranov-sas-sakroveniya-v-burgas-3514
headline: Емблематичният Орлин Горанов със Съкровения в Бургас
P1: Емблематичният глас на българската естрадна музика - Орлин Горанов гостува в Бургас с концерта "Съкровения". Музикалният празник е на 24-ти август от 20.30 часа в Летния театър, а негов организатор е "Арт Мелпомена".
LAST: Билети се продават на каса "Часовника", както и онлайн.
(npara=5, nchar=575)

#### 3c6f88ff87e8fc11 | 2025-08-19 | Черноморие-бг | Култура
url: https://chernomorie-bg.com/post/bon-bon-otpraznuva-30-godini-na-morska-scena-v-carevo-4888
headline: Бон-Бон отпразнува 30 години на Морска сцена в Царево
P1: Група "Бон-Бон" отпразнува 30 години на Морска сцена в Царево. Градът бе включен в националното турне на формацията, озаглавено "Нещо ново".
LAST: "Бон-Бон" ще гостува в Лозенец на 20-ти август.
(npara=5, nchar=841)

#### 4866fe30dd8d591d | 2026-06-08 | Черноморие-бг | Туризъм
url: https://chernomorie-bg.com/post/105-got-obyavyavaneto-na-varna-za-kurorten-grad-4496
headline: 105 г.от обявяването на Варна за курортен град
P1: Варна ще отбележи 105 години от обявяването си за курортен град – значима годишнина, която подчертава развитието на морската столица като един от най-важните туристически центрове в България.
LAST: Днес Варна остава символ на съчетанието между история, култура, море и минерална вода – място, което съхранява и развива своята идентичност като водеща туристическа дестинация в България.
(npara=8, nchar=2464)

#### e35e924bab9968e4 | 2026-09-01 | Черноморие-бг | Култура
url: https://chernomorie-bg.com/post/varnensko-lyato-prodaljava-sas-simpozium-konferenciya-i-forum-na-evropeyskata-festivalna-asociaciya-7053
headline: Варненско лято продължава със симпозиум, конференция и форум на Европейската фестивална асоциация
P1: С поредица от събития продължава юбилейната програма на Международния музикален фестивал „Варненско лято" през първата седмица на септември.
LAST: Шестте дни допълват юбилейната програма на „Варненско лято" с международен обмен, професионални срещи и концерти с участието на водещи музиканти и представители на фестивалната общност от България и Европа.
(npara=6, nchar=2298)

#### a2c2e9d34dfc600b | 2026-08-27 | Черноморие-бг | Култура
url: https://chernomorie-bg.com/post/vav-varna-zapochna-34-oto-izdanie-na-lyubovta-e-ludost-6517
headline: Във Варна започна 34-ото издание на Любовта е лудост
P1: 34-ото издание на Международния филмов фестивал "Любовта е лудост" започна снощи във Варна. Откриващата вечер във Фестивалния и конгресен център събра представители на културните институции, кинотворци, официални гости и почитатели на седмото изкуство. Сред тях бяха кметът на Варна Благомир Коцев, заместник-кметът София Колева, директорът на НДК Ия Петкова, фестивалният директор Димитър Стоянович, създателят на фестивала проф. Александър Грозев, както и членовете на журито - Владимир Пенев, Жана
LAST: Повече информация на адрес: https://loveisfolly.eu/programa/
(npara=7, nchar=2123)

### 2 contrasting articles (NOT this voice/mode)
- 11ca6a679e85e3b8 | 2025-08-19 | Черноморие-бг | Култура | headline: Емблематичният Орлин Горанов със Съкровения в Бургас | url: https://chernomorie-bg.com/post/emblematichniyat-orlin-goranov-sas-sakroveniya-v-burgas-3514
- 2ba12a8ede485a3c | 2022-10-22 | Черноморие-бг | Общество | headline: 20° температури се завръщат от днес | url: https://chernomorie-bg.com/post/20-temperaturi-se-zavrashtat-ot-dnes-5906

### Editor verdict
- KEEP / MERGE(->which?) / DROP + one-line reason
---

## MODE_CULTURE_FEATURE [story_mode, PROVISIONAL, n=17] - Culture feature (long)
Scope: category Култура, 6+ paras (n=17); cross-author
Preferred use: Long culture reports: festival/concert/theatre roundups with program, cast, prizes, funders.
Sources: authors=['Черноморие-бг', 'Десислава Георгиева']; categories=['Култура']
Headline: Event + place form: 'Епопея на забравените с премиера през септември в бургаския театър'.; Edition form: 'Деветото издание на Порт Прим Арт Фест започва на 7 октомври'.; Occasional quoted title in headline (~6%, only profile where it survives in recent data).
Opening: Scene/result opening (immediate_fact 11/17); quote_first allowed (1/17) - only profile where a quoted-title opening is acceptable.; Legacy headline-repeat opening appears only in pre-2020 members (3/17); do NOT imitate it in new drafts.
Body: 6+ paragraphs (median 7), median body ~2100 chars; P1 ~300 chars, closing ~150-190. Relatively long sentences observed, median ~17.3 words; list-like cast/program sentences. Episodic: result -> acts/program -> cast/names -> money/prize -> funders/closing line.
Quotes: Relatively high quote density observed (~8.7/1000): titles, speech, mottos. Titles in P1; speech quotes in P2-P5.
Tone: Factual base with celebratory adjectives ('зрелищно', 'вдъхновяващ', 'вкусна') - only profile where they are conventional. Closest of the set, but still third person.
Numbers/dates: Edition numbering ('Деветото издание', '34-ото издание').; Prize/money lines kept ('премията от 12 000 лева', '6 000 лева получи екипът...').; Cast lists as comma chains in one paragraph.
Lexicon: 'премиера', 'издание', 'фестивал', 'спектакъл', 'участват', 'програма', 'награда/премия', 'с подкрепата на'.
Avoid (tendencies, not hard rules): Avoid compress to 3-5 news paras.; Avoid drop cast/program/prize detail.; Avoid use blotter attribution formula.; Avoid imitate pre-2020 headline-repeat opening in new drafts.
Evidence: Culture-long n=17: body ~2100ch; 7 paras med; sentences ~17.3w (longest observed); quote density ~8.7/1000 (highest observed); celebratory adjectives most visible here. Legacy headline-repeat members (3/17, pre-2020) are documented drift, not a target for new drafts.

### 5 representative articles (read headline + P1 + last para)

#### eb3262c0b6935eb6 | 2009-08-02 | Десислава Георгиева | Култура
url: https://chernomorie-bg.com/post/-20-
headline: Екипът на “Летя” спечели 20 бона на “Бургас и морето”
P1: Екипът на “Летя” спечели 20 бона на “Бургас и морето”
LAST: Освен наградите на жури и публика бе присъдена и още една награда – на бургаските медии. Те определиха за неин носител песента “Когато мъжете плачат” по музика на Бончо Гроздев и текст на Пейо Пантелеев. Баладата бе изпята от Галя Ичеренска.
(npara=7, nchar=1593)

#### 159770f19be306dd | 2025-08-20 | Черноморие-бг | Култура
url: https://chernomorie-bg.com/post/epopeya-na-zabravenite-s-premiera-prez-septemvri-v-burgaskiya-teatar-7720
headline: Епопея на забравените с премиера през септември в бургаския театър
P1: "Епопея на забравените" по Иван Вазов ще има своята премиера на 18-ти септември на сцената на бургаския драматичен театър "Адриана Будевска". Драматургичният текст е на Емил Бонев, режисьор е Богдан Петканин, художник на декор - Милен Боричев, художник на костюмите - Жанета Иванова, музика - Георги Гарчов
LAST: Проектът е реализиран с финансовата подкрепа на Министерството на културата.
(npara=7, nchar=1627)

#### 72b6d5ede6c40f5d | 2019-03-20 | Десислава Георгиева | Култура
url: https://chernomorie-bg.com/post/osem-drujestva-i-konsorciumi-iskat-da-remontirat-nhk-2024
headline: Осем дружества и консорциуми искат да ремонтират НХК
P1: Осем специално създадени дружества и консорциуми участват в обществената поръчка на Община Бургас, която е с предмет - "Реконструкция, ремонт и обновяване, внедряване на мерки за енергийна ефективност в Културен дом на Лукойл Нефтохим - град Бургас". Поръчката бе обявена на 31-ви декември миналата година и срокът й изтече на 19-ти март. Поради големия интерес към нея обаче срокът бе удължен до края на февруари. До крайната дата оферти са подали - консорциум "Геоплан инфраструктура", ДЗЗД "БМ", Д
LAST: След основният ремонт, в залата местата ще бъдат редуцирани с десетина, а тя ще разполага с възможности за кино прожекции. Така ще се сбъдне една стара мечта в града да има общинско кино. В момента Общинското кино "АБ" се помещава в залата на драматичен театър "Адриана Будевска", където се провежда 
(npara=6, nchar=2010)

#### de1feb5a5c626507 | 2026-07-20 | Десислава Георгиева | Култура
url: https://chernomorie-bg.com/post/romantichna-istoriya-ot-60-te-otkriva-burgaskiya-filmov-festival-5106
headline: Романтична история от 60-те открива бургаския филмов фестивал
P1: Романтична история от края на 60-те години на миналия век открива тази вечер 11-то издание на "Burgas International Film Festival" (BIFF). Документалният филм "Снежа и Франц" на режисьора Светослав Драганов ще бъде показан на открита сцена Охлюва от 21.30 часа. С тази прожекция ще бъде сложено началото на тазгодишното издание на фестивала, който за първи път започва в понеделник и ще приключи в събота.
LAST: Събитието се организира от фондация "Модерат" с финансовата подкрепа на Община Бургас и медийното партньорство на сайт "Черноморие-бг".
(npara=10, nchar=2396)

#### a2c2e9d34dfc600b | 2026-08-27 | Черноморие-бг | Култура
url: https://chernomorie-bg.com/post/vav-varna-zapochna-34-oto-izdanie-na-lyubovta-e-ludost-6517
headline: Във Варна започна 34-ото издание на Любовта е лудост
P1: 34-ото издание на Международния филмов фестивал "Любовта е лудост" започна снощи във Варна. Откриващата вечер във Фестивалния и конгресен център събра представители на културните институции, кинотворци, официални гости и почитатели на седмото изкуство. Сред тях бяха кметът на Варна Благомир Коцев, заместник-кметът София Колева, директорът на НДК Ия Петкова, фестивалният директор Димитър Стоянович, създателят на фестивала проф. Александър Грозев, както и членовете на журито - Владимир Пенев, Жана
LAST: Повече информация на адрес: https://loveisfolly.eu/programa/
(npara=7, nchar=2123)

### 2 contrasting articles (NOT this voice/mode)
- eb3262c0b6935eb6 | 2009-08-02 | Десислава Георгиева | Култура | headline: Екипът на “Летя” спечели 20 бона на “Бургас и морето” | url: https://chernomorie-bg.com/post/-20-
- 2ba12a8ede485a3c | 2022-10-22 | Черноморие-бг | Общество | headline: 20° температури се завръщат от днес | url: https://chernomorie-bg.com/post/20-temperaturi-se-zavrashtat-ot-dnes-5906

### Editor verdict
- KEEP / MERGE(->which?) / DROP + one-line reason
---

## Rejected / merged candidates
- Flat five-as-equals taxonomy (HOUSE_NEWS/HOUSE_BRIEF/CULTURE_FEATURE/EVENT_PREVIEW/DESISLAVA_REPORTAGE as peers): SUPERSEDED by VOICE+MODE composition (legacy mapping kept in style_composition.json).
- Per-author profile for every author: REJECTED (only Desislava recent clears a provisional voice; unknown n=8 insufficient).
- Per-category Sport/Tourism/Business/Education standalone modes: REJECTED (n=12-17, overlap standard news; retrieval context only).
- Annual styles: REJECTED (drift note instead; M2.3 prefers 2020-2026 practice).
- Legacy-Desislava selectable voice: REJECTED (pre-2020 headline-repeat 64% + quoted headlines 24% is CMS-era practice; documented drift, excluded from VOICE_DESISLAVA_RECENT scope).
- EVENT_PREVIEW x CULTURE_FEATURE merge: REJECTED (announcement task vs report task; retrieval disambiguates by forward-looking intent).
