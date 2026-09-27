"""V1.2-G2.3 §9-§12: which sentences may even be considered a fact.

Two narrow jobs, both deterministic and both BEFORE any promotion:

* **Content quality (§11/§12).** Reject navigation chrome, cookie banners,
  footer and category lists, and text that is not shaped like a proposition.
  G2.1's single promoted "fact" was a navigation menu, so this is a measured
  failure, not a hypothetical one.
* **Bounded multi-claim extraction (§9/§10).** Return a small candidate set per
  opened page instead of the first matching sentence, each associated with the
  research question it can answer, so corroboration can compare like with like
  (§7, §22).

Nothing here decides whether a claim is TRUE, and nothing here grants
authority. It only removes text that cannot be a fact.
"""

from __future__ import annotations

import re

from editor_assistant.workflow.claim_equivalence import _key

#: §11 — the G2.1 false success, kept verbatim so the regression is permanent.
KNOWN_CHROME = "НОВИНИ КУЛТУРНА ПРОГРАМА СПОРТНА ПРОГРАМА"

#: §27 — real promoted facts from the 24-Story replay that were NOT facts. Every
#: one of these reached the evidence basis before the filters below were added,
#: so each is kept verbatim as a named regression.
KNOWN_BOILERPLATE = (
    (
        "Всички статии, репортажи, интервюта и други текстови, графични и видео "
        "материали, публикувани в сайта, са собственост на редакцията."
    ),
    (
        "Този уебсайт е собственост на Sportal Media Group За нас За реклама "
        "Общи условия Лични данни Управление на персонала."
    ),
    (
        "Прочети в sportal.bg Бургастенис турнирМорската градина Всички "
        "публикации (1) sportal.bgпреди 5 дни Black Sea Open."
    ),
    (
        "Black Sea Open събира най-добрите тенис любителите идния уикенд в Бургас "
        "| Топ Новини НАЧАЛОБЪЛГАРИЯСВЯТБИЗНЕС"
    ),
    (
        "На 22 септември 1908 година в църквата… Новото издание на конкурса за "
        "поезия „Бургас вдъхновява“ дава поле за"
    ),
)

#: §11/§27 — ownership, cookie, legal-notice and breadcrumb boilerplate, each
#: learned from text that the 24-Story replay actually promoted.
_BOILERPLATE_PATTERNS = (
    r"публикувани в сайта|собственост на\s|този уебсайт е|всички права запазени",
    r"прочети в\s|прочети още|виж още|всички публикации|всички новини",
    (
        r"на основание чл\.|съгласно чл\.|влизат в сила|могат да се оспорят|"
        r"обжалват от|вносител на промените|заместник кмет"
    ),
    r"общи условия|лични данни|политика за поверителност|за реклама\b",
    r"\b\w+\.(бг|ком|net|org|eu)\b",          # a bare domain inside prose
    r"\|\s*(топ\s+)?новини\b|топ новини",
    r"категории|архив\s*:|тагове?:",
    # §27 - a run of hashtags is a tag cloud, never a proposition. This is the
    # one remaining chrome item from the review: "#катастрофа ... Новини Нашите
    # инициативи БНР ...".
    r"(?:\s*#\w+){2,}",
)

# --- V1.2-G2.4 §A3: the generalised tag-cloud / widget filter ---------------
#
# G2.3 fixed exactly the observed string. §A3 requires the *class* to fail, not
# the one sample, and warns against over-filtering legitimate short sentences.
# The four shapes below are the classes the observed blob is made of, and each
# one is a property of the TEXT, not of a particular publisher:
#
#   1. a hashtag anywhere  — a real Bulgarian sentence never contains "#";
#   2. a hashtag-plus-navigation run — the observed "#катастрофа … Новини
#      Нашите инициативи БНР …", where a tag is fused to a category run;
#   3. a share/follow component — "Сподели статията", "Следвай ни", "Харесва";
#   4. a recommendation widget — "Препоръчано за вас", "Още от автора",
#      "Повече новини от", "Свързани статии".
#
# Every pattern is anchored on a marker token that cannot legitimately occur in
# a factual proposition in this form, so a genuine short sentence is never lost.
_TAG_CLOUD_PATTERNS = (
    # 1. any hashtag token. `#` is never part of Bulgarian prose.
    r"#\w",
    # 3. share / follow components.
    (
        r"сподели статия|споделете статия|харесва(йте)?\s+страницата|следвай(те)?\s+ни|"
        r"свали приложението|абонирай(те)?\s+за"
    ),
    # 4. recommendation widgets.
    (
        r"препоръчано за вас|още от автора|повече (новини|статии) от|свързани статии|"
        r"прочетете още|вижте още"
    ),
)

#: 2. a navigation/category run: three or more short Title-Case labels with no
#: sentence punctuation. Matched on the ORIGINAL case on purpose — capitalisation
#: is the only signal it has — so it is kept apart from the case-insensitive word
#: markers above.
#: --- §A2 (second pass): segmentation ARTEFACTS that survive semantic markup --
#:
#: The typed segmentation (§A2) stops a merge when the page uses real headings.
#: Measured on the frozen sample, the surviving defects are two classes, and both
#: are properties of the TEXT, not of any one publisher:
#:
#: 1. **An accessibility skip link.** "Skip to content" is a `<a>` that exists to
#:    let keyboard users bypass the menu. It is chrome in every language, and a
#:    Bulgarian site carries the English marker verbatim.
#: 2. **A glued token run.** When a page concatenates inline nodes with no
#:    whitespace — a date, a counter and a breadcrumb glued together — the result
#:    is `сеп.212026ПресцентърСпорт` or `2 публикацииНа 21 септември`. Digits
#:    touching a capital letter, or a capitalised word touching another word, is
#:    proof that two nodes were concatenated by the renderer and NOT by an author.
#:    No Bulgarian sentence contains either.
_SKIP_LINK = re.compile(
    r"\bskip\s*to\s*content\b|\bкъм\s+съдържанието\b|\bпрескочи\s+към\s+съдържанието\b",
    re.IGNORECASE,
)

#: Proof of a whitespace-less node boundary inside the text.
#:
#: Two independent signatures, because a single digit-then-capital adjacency is
#: NOT enough: Bulgarian legal and administrative references use it constantly
#: ("чл. 5Б", "Решение 12А", "Отдел 3Б"), and an earlier version of this rule
#: rejected every one of them — real sentences, on council stories in particular.
#: The artefact is a *whole run* of concatenated nodes, so the digit rule demands
#: a token that is long enough to be a run and not a citation.
_GLUED_TOKEN = re.compile(
    # a long token mixing digits and capitals: `212026ПресцентърСпорт`
    r"\b\w*[0-9]\w*[А-ЯЪ]\w{3,}\b"
    # a lowercase word run glued to a new capitalised word: `публикацииНа`
    r"|[а-я]{3}[А-ЯЪ]"
    # a closing bracket glued to the next word
    r"|\)[А-ЯЪ]"
)

_NAV_RUN_CLOUD = re.compile(
    r"(?:\b[А-Я][а-я]{2,}(?:\s+[А-Я][а-я]{2,}){0,2}\b[\s|/]+){3,}"
)

#: A real proposition carries function words and a verb. A navigation or
#: breadcrumb blob is a Title-Case run with almost none, which is what let the
#: items above through.
_FUNCTION_WORDS = frozenset(
    ["и", "или", "но", "че", "да", "се", "на", "в", "за", "от", "по", "при", "през", "след", "преди", "около", "към", "пред", "между", "без", "дори", "само", "пък", "вече", "днес", "утре", "вчера", "много", "най", "повече", "по-малко", "това", "този", "тази", "тези", "също", "са", "беше", "били", "има", "няма", "ще", "може", "трябва", "бяха", "станаха", "техен", "негов", "нея", "тя", "те", "вие", "ние", "ви", "аз", "той", "тя", "то", "тех", "този", "тази"]
)

_CHROME_PATTERNS = (
    r"doctype|<\s*html|<\s*body|<\s*div|<\s*a\s|cookie|бисквитк",
    r"\bnav\b|\bменю\b|\bнавигац|хлебни трохи|\bхлебни\b",
    r"вход\s*[:·]|\blogin\b|регистрац|\bабонирайт|\bабони|\bсподеляне\b",
    r"^\s*(обяви|контакти|реклама|рекламна|задължителна|условия за|поверителност)",
    r"всички права запазени|©|\bcopyright\b|всички изображения са",
)
_CATEGORY_ONLY = re.compile(
    r"^[\sА-ЯA-Zа-яa-z0-9&-]{0,400}$"
)
#: §9/§27 - page text must be split into propositions BEFORE any claim is read.
#: Splitting only on [.!?] merged unrelated sentences whenever an abbreviation or
#: an ellipsis sat between them ("...дава поле за ... Темата тази година е... целта
#: на конкурса е да… Лесотехническият университет..."), which is how two
#: different stories became one "fact". An ellipsis and a legal citation both
#: end a proposition.
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|(?<=\.\.\.)\s+|\s+(?=т\.\s?\d|ал\.\s?\d|чл\.\s?\d)")


#: A run of short all-caps labels with no sentence punctuation is a menu bar.
_MENU_RUN = re.compile(r"(?:\b[А-ЯЪ]{3,12}\b[\s|/]+){3,}")
_SENTENCE_END = re.compile(r"[.!?…]")
_TERMINAL_PUNCT = re.compile(r"[.!?…»”\"']\s*$")
#: A copula or auxiliary in first position: the clause has lost its subject.
#: A clause that starts mid-thought is an extraction artefact, not a
#: proposition.
#:
#: Deliberately the copula/auxiliary set G2.3 validated, and nothing more. An
#: earlier attempt also rejected a leading preposition (to catch "от 9:00 часа,
#: в заседателната зала…"), and it was reverted because it cost real facts:
#: "На 21 септември се отбелязва…" and "В Бургас денят беше отбелязан…" are
#: complete Bulgarian sentences that open with the very words the rule would
#: refuse. One remaining marginal fragment is reported as QUESTIONABLE in the
#: report instead of being bought with a false-positive rate.
_FRAGMENT_START = re.compile(
    r"^(?:и|или|но|а|че|да|се|е|са|бе|би|бяха|ще|били|имат|няма)\b", re.IGNORECASE
)

#: §A2 third pass — a TRUNCATED PREVIEW. A "read more"/teaser line ends in an
#: ellipsis because the publisher cut it: "… започва подготовката за 2027 г.,
#: когато Бургас ще…". It states no complete proposition, so it is chrome. A
#: genuine sentence is published whole, and the frozen sample's real facts all
#: end in a full stop.
_TRUNCATED_PREVIEW = re.compile(r"[…]\s*[»”\"')\]]?\s*$")
_MIN_CHARS = 25
_MAX_CHARS = 600

#: §10 — which research question a candidate answers, and the answer shape that
#: makes a sentence a plausible answer to it.
_DIMENSIONS = {
    "event_schedule": (
        r"\bкога\b|\bграфик\b|\bдата\b|\bвреме\b|програм",
        r"\b\d{1,2}[.:]\d{2}\s*ч\b|\b\d{1,2}\s+(?:януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември)\b|\b\d{4}\s*г|\bпрез\b",
    ),
    "participants": (
        r"\bкой\b|\bкои\b|\bорган\b|\bлице\b|\bзамесен",
        r"\bкмет\w*|\bминистър\w*|\bсъвет\w*|\bкомиси\w*|\bдиректор\w*|\bсъд\w*|\bполици\w*",
    ),
    "venue": (
        r"\bкъде\b|\bзал\b|\bадрес\b|\bплощад\b|\bобласт\b|\bград\b|\bсело\b",
        r"\bна\b|\bв\b|\bул\.|\bбулевард|\bплощад|\bград|\bсело|\bобласт",
    ),
    "amount": (
        r"\bколко\b|\bсума\b|\bфинанс|\bцена\b|\bлева\b|\bевро\b",
        r"\b\d[\d\s.,]*\s*(?:лева|лв|евро|милиона?|милион|млн\.?|млрд\.?|хиляди|хиляда|хил\.?|%)\b",
    ),
    "decision_status": (
        r"\bрешение\b|\bрешен\b|\bприет|\bодобрен|\bотхвърлен|\bстатус",
        r"\bприет|\bодобр|\bотхвърл|\bрешени|\bпостанови|\bзабрани|\bразреши",
    ),
}


def is_chrome(text: str) -> bool:
    """True when the text is page furniture rather than content (§11)."""
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.casefold()
    for pattern in _CHROME_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            return True
    for pattern in _BOILERPLATE_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            return True
    # §A3: the generalised tag-cloud / widget classes. The word markers are
    # matched case-insensitively; the Title-Case navigation run is matched on
    # the ORIGINAL case, because capitalisation is the only signal it has. Both
    # are anchored on markers that cannot occur in a genuine proposition.
    for pattern in _TAG_CLOUD_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            return True
    if _NAV_RUN_CLOUD.search(value):
        return True
    # §A2 second pass: an accessibility skip link, and any whitespace-less node
    # boundary. Both are renderer artefacts, and neither can occur in a sentence
    # an author wrote.
    if _SKIP_LINK.search(value) or _GLUED_TOKEN.search(value):
        return True
    # An all-caps label run is chrome even when the block ends in a full stop,
    # which is exactly how "… в Бургас | Топ Новини НАЧАЛОБЪЛГАРИЯСВЯТБИЗНЕС"
    # reached the evidence basis.
    if re.search(r"(?:[А-ЯЪA-Z]{3,}[\s|/—-]*){3,}", value):
        return True
    if _MENU_RUN.search(value):
        return True
    # A block of bare all-caps labels separated by whitespace/pipes is a menu.
    letters = re.sub(r"[^A-Za-zА-Яа-я]", "", value)
    # A block of bare all-caps labels with no sentence punctuation is a menu bar.
    if (
        letters
        and sum(ch.isupper() for ch in letters) / len(letters) > 0.7
        and not _SENTENCE_END.search(value)
    ):
        return True
    # A real navigation bar is often title case, not caps: a run of short
    # one-or-two word labels separated by wide spacing, with no sentence
    # punctuation. `Начало   Новини   Култура   Спортна програма` is the shape.
    if not _SENTENCE_END.search(value):
        labels = [part for part in re.split(r"\s{2,}|[|/]", value) if part.strip()]
        if len(labels) >= 3 and all(len(part.split()) <= 3 for part in labels):
            return True
    return False


def is_factual_candidate(text: str) -> bool:
    """True when the text is shaped like a proposition (§12).

    Conservative guards only: a minimum length, a sentence ending, and a real
    proportion of letters. Short but legitimate facts are not rejected merely
    for being short - the floor is deliberately low.
    """
    value = str(text or "").strip()
    if not value or is_chrome(value):
        return False
    if not (_MIN_CHARS <= len(value) <= _MAX_CHARS):
        return False
    # §12/§27 — a fact is a COMPLETE proposition, so the text must END with
    # sentence punctuation. Merely containing one is not enough: a `read more`
    # preview can hold a finished sentence and still stop mid-phrase, and that
    # is how "...в църквата… Новото издание ... дава поле за" reached the
    # evidence basis in the 24-Story replay.
    if not _TERMINAL_PUNCT.search(value):
        return False
    # §27 - a clause that starts mid-thought is an extraction artefact, not a
    # proposition. "е пострадал при катастрофа на пътя Стара Загора..." is the
    # tail of a sentence whose subject was lost, and it was promoted as a fact.
    if _FRAGMENT_START.match(value):
        return False
    # §A2: a truncated preview is not a fact, however well-formed it looks.
    if _TRUNCATED_PREVIEW.search(value):
        return False
    letters = re.findall(r"[A-Za-zА-Яа-я]", value)
    if len(letters) < 0.5 * len(value.replace(" ", "")):
        return False
    # A proposition carries verbs-ish word variety; a bare fragment of two
    # repeated words is not one.
    tokens = [w.casefold() for w in re.findall(r"[\wа-яА-Я]+", value)]
    words = {word for word in tokens if len(word) > 2}
    if len(words) < 4:
        return False
    # §12/§27 — a proposition is built from function words. A blob assembled
    # from labels and names has almost none, however long it is. These are short
    # words, so the presence test deliberately uses EVERY token, not the
    # content-word subset above.
    if not set(tokens) & _FUNCTION_WORDS:
        return False
    return True


def answering_dimensions(sentence: str, questions) -> set[str]:
    """Which research dimensions this sentence can plausibly answer (§10, §22)."""
    question_blob = " ".join(str(q or "") for q in questions).casefold()
    sentence_blob = str(sentence or "").casefold()
    out = set()
    for name, (question_pattern, answer_pattern) in _DIMENSIONS.items():
        if re.search(question_pattern, question_blob, re.IGNORECASE) and re.search(
            answer_pattern, sentence_blob, re.IGNORECASE
        ):
            out.add(name)
    return out


#: §10 - a claim is a candidate because it is about THIS Story, not because it
#: happens to contain a date or a number. A sentence that shares almost nothing
#: with the Story's own subject is an interesting sentence about something else,
#: and promoting it is how "Дом, в който влизат лазарки..." ends up as a fact of
#: a poetry contest. The threshold is deliberately low so a genuine fact stated
#: in different words still qualifies.
#: One shared content key is the line. Measured on the 24-Story replay: the
#: unrelated sentences that had been promoted shared NOTHING with their Story
#: ("Дом, в който влизат лазарки..." against a poetry contest; "Точно преди 118
#: години..." against the same), while the genuine ones share at least one
#: ("ремонтът" in a Story about the street repair). Two was measured too
#: strict and threw real facts away.
_TOPIC_KEYS_REQUIRED = 1

#: Keys that never identify a Story on their own. Measured on the 24-Story
#: replay: "Лесотехническият университет открива филиал в Бургас" shared exactly
#: one key with "Млади творци ... Бургас вдъхновява" - the city. A place, a year
#: or a weekday links two completely different stories, so these never count
#: towards relevance. The distinctive word of a Story (here "вдъхновява") does.
_GENERIC_KEYS = frozenset(
    [
        "бург", "бургас", "варна", "софия", "пловдив", "българия", "българск",
        "български", "година", "години", "годишен", "ден", "дни", "денят",
        "месец", "час", "часа", "седмица", "новини", "новина", "статия", "сайт",
        "интернет", "град", "села", "област", "улица", "улици", "път", "пътища",
        "градове", "страна", "страни", "хора", "работа", "работят",
    ]
)


# --- V1.2-G2.4 §A4: event-context agreement -------------------------------
#
# G2.3 promoted a sentence about the Stara Zagora–Kazanlak accident into the
# Burgas–Sozopol Story. `_is_about` did not stop it because the two sentences do
# share a content key with the Story — `катастрофа` — and §A4 states plainly that
# a single generic shared word is never sufficient.
#
# The rule is anchor agreement, not similarity: a candidate must agree with the
# Story event on enough *identifying* anchors, and a hard contradiction on a
# locality or a date rejects it outright without a model. The anchors below are
# deliberately the ones §A4 names: central entities, locality, event/action,
# date and a key quantity. Words that can describe any news story at all
# (`катастрофа`, `новости`, `събитие`) are excluded from every anchor set, so
# sharing one can never produce agreement.

#: Words that identify no event. They occur in any two unrelated stories, so
#: they can never count towards anchor agreement. §A4 names `катастрофа`; this
#: is the generalisation of that one word into the whole class of generic news
#: vocabulary. The list is keyed through the SAME `_key` as the anchors, so a
#: surface form like "събитието" and its stem "събити" cannot slip past by
#: inflection.
_GENERIC_NEWS_WORDS = (
    "катастрофа", "катастрофи", "катастрофен", "новости", "новина", "събитие",
    "събития", "събитието", "събитие", "съобщение", "съобщения", "статия",
    "статии", "инцидент", "инциденти", "инцидента", "път", "пътя", "пътища",
    "пътят", "българска", "български", "българия", "българският", "днес",
    "вчера", "утре", "година", "години", "годишен", "събит", "произшествие",
    "според", "източник", "източници", "публикация", "медия", "медиите",
    "новинар", "кореспондент", "кот", "същата", "този", "тази", "тези",
    "това", "новинарка", "съобщи", "съобщава", "представи", "представя",
    "пострадаха", "загина", "ранени", "тежко", "леко", "тежка", "лека",
)
_NEVER_ANCHOR = frozenset(_key(word) for word in _GENERIC_NEWS_WORDS)

#: §A4: a claim must share at least this many NON-GENERIC anchors with the Story.
#:
#: One is the correct number, and it is worth being precise about why. §A4's
#: actual requirement is that a generic shared word — `катастрофа` by name —
#: must never be sufficient, and that is enforced by the *blocklist*, not by the
#: count: generic words are removed from every anchor set, so they can never be
#: the shared anchor. Requiring TWO on top of that was measured to reject real
#: facts of the same event ("Ранени при инцидента са 30-годишна жена и
#: момиченце" shares only `жена` with its own Story) while adding no safety the
#: road-locality contradiction below does not already provide.
_MIN_IDENTIFYING_ANCHORS = 1

#: §A4: a Story needs at least this many anchors before the anchor gate can
#: discriminate one event from another. A short or generic subject ("Тест
#: история") yields a two-word anchor set that no genuine sentence about the
#: real event would share, so arming the gate there would reject every correct
#: claim without rejecting anything wrong. The gate is therefore only armed when
#: the Story itself is specific enough to identify an event, and the historical
#: topic-overlap check stands in otherwise. This errs in the conservative
#: direction: it can never manufacture agreement, only decline to demand it.
_MIN_IDENTIFYING_ANCHOR_SET = 4

#: A road / route phrase: "пътя Бургас-Созопол", "пътя Стара Загора – Казанлък".
#: The dash-joined capitalised pair is a high-precision locality signal, so it
#: is used ONLY for a contradiction test and never for agreement. Detecting
#: "any capitalised word" would over-filter ordinary sentences, which §A3
#: explicitly forbids.
_ROAD_PLACES = re.compile(
    r"\bпът(?:я|ят|ят|ища|ищата)?\s+"
    r"([А-Я][а-я]+(?:[\s–—-]+[А-Я][а-я]+){0,2})",
    re.IGNORECASE,
)


def _content_keys(value: str) -> set[str]:
    """Stemmed, non-generic content keys of one text."""
    return {
        _key(word)
        for word in re.findall(r"[\wа-яА-Я]+", str(value or "").casefold())
        if len(word) > 3
    } - _NEVER_ANCHOR


def _road_localities(value: str) -> set[str]:
    """The place names a road/route phrase names, e.g. a road accident's route."""
    out: set[str] = set()
    for match in _ROAD_PLACES.finditer(str(value or "")):
        for word in re.findall(r"[А-Я][а-я]{2,}", match.group(1)):
            key = _key(word.casefold())
            if len(key) >= 3:
                out.add(key)
    return out


def event_anchors(*texts: str) -> set[str]:
    """The identifying anchor keys of a Story event.

    Built from the Story's own canonical text (its cleaned title and the
    representative publication). Generic news vocabulary is removed by the same
    keyed blocklist, so what survives is specific: a named person, a named
    organisation, a named place, a distinctive action or quantity word.
    """
    out: set[str] = set()
    for text in texts:
        out |= _content_keys(text)
    return out


def agrees_with_event(sentence: str, anchors: set[str], *, topic: str = "") -> bool:
    """True when the sentence is about the SAME event as the anchors.

    Two ordered checks, both deterministic and both BEFORE any model call:

    1. **Hard contradiction.** When the Story names a road/route locality and
       the claim names a different one, they are different events. §A4 requires
       contradictions to bypass the model and reject immediately, and this is
       the check that stops a Stara Zagora–Kazanlak sentence inside the
       Burgas–Sozopol Story deterministically.
    2. **Identifying anchor agreement.** The claim must share at least one
       non-generic anchor. A generic shared word such as `катастрофа` can never
       satisfy this, because generic vocabulary is removed from every anchor set
       on both sides — it is the WORD that is disallowed, not the count.

    A Story with no usable anchors cannot discriminate events at all, so the
    historical non-filtering behaviour is kept rather than rejecting everything.
    The same holds when the anchor set is too small to identify an event
    (`_MIN_IDENTIFYING_ANCHOR_SET`): the gate stays unarmed rather than armed
    against a subject it cannot describe.
    """
    text = str(sentence or "")
    if not text.strip() or not anchors:
        return True

    # 1. Road-locality contradiction — no model, no similarity, no chance.
    topic_places = _road_localities(topic or "")
    if topic_places:
        claim_places = _road_localities(text)
        if claim_places and not (claim_places & topic_places):
            return False

    # 2. Identifying anchor agreement. Only demanded when the Story's own
    #    subject is specific enough for the demand to mean anything.
    if len(anchors) < _MIN_IDENTIFYING_ANCHOR_SET:
        return True
    return len(_content_keys(text) & anchors) >= _MIN_IDENTIFYING_ANCHORS


def _is_about(sentence: str, topic: str) -> bool:
    """True when the sentence shares its subject with the Story."""
    subject = {
        _key(word)
        for word in re.findall(r"[\wа-яА-Я]+", str(topic or "").casefold())
        if len(word) > 3
    }
    subject -= _GENERIC_KEYS
    if not subject:
        # No usable subject (an empty or very short title): relevance cannot be
        # judged, and the historical behaviour of not filtering is kept.
        return True
    sentence_words = {
        _key(word)
        for word in re.findall(r"[\wа-яА-Я]+", str(sentence or "").casefold())
        if len(word) > 3
    }
    return len(subject & sentence_words) >= _TOPIC_KEYS_REQUIRED


#: §A2 — block kinds that may carry a factual sentence. Everything else
#: (HEADING, LIST_ITEM, LABEL, NAV) is furniture: readable, useful as context,
#: never a proposition on its own and never concatenated into one.
_PROSE_KINDS = frozenset({"PROSE"})


def select_candidate_claims(
    sentences,
    questions,
    *,
    limit: int = 4,
    topic: str = "",
    blocks=None,
    anchors: set[str] | None = None,
) -> list[dict]:
    """A small, ordered candidate set from one opened page (§9, §10, §A2, §A4).

    At most ``limit`` claims (3-5 by default) are returned, each with the
    dimension it answers, so corroboration compares claims that were extracted
    for the same reason rather than arbitrary sentences. The order is by
    relevance to the Story's questions, and duplicates are dropped.

    `blocks` is the typed segmentation from `html_desc.normalize_blocks`. When
    given, only `PROSE` blocks are read, which is what structurally prevents a
    heading-plus-sentence merge. When it is absent the caller is passing plain
    sentences and the historical behaviour is kept.

    `anchors` is the Story's event-anchor set (§A4). When given, a well-formed
    sentence that does not agree with the Story's event is dropped here — before
    claim comparison and before any model call.
    """
    pool = []
    seen = set()
    if blocks is not None:
        # A PROSE block is a paragraph, not a sentence, so it is still split —
        # but every resulting sentence inherits the block's kind, which is what
        # keeps a heading out of the pool no matter how the page is marked up.
        units: list[tuple[str, str | None]] = []
        for block in blocks:
            text = str(block.get("text") or "")
            kind = str(block.get("kind") or "")
            if kind in _PROSE_KINDS:
                units.extend((part, kind) for part in SENTENCE_SPLIT.split(text))
            else:
                units.append((text, kind))
    else:
        units = [(str(raw or ""), None) for raw in sentences or []]
    for index, (raw, kind) in enumerate(units):
        value = raw.strip()
        if not value:
            continue
        if kind is not None and kind not in _PROSE_KINDS:
            # §A2: a heading, list item, label or navigation run is context, not
            # a proposition. Splitting it is what produced the merged "facts".
            continue
        if not is_factual_candidate(value):
            continue
        if not _is_about(value, topic):
            continue
        if anchors is not None and not agrees_with_event(value, anchors, topic=topic):
            continue
        marker = value.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        dimensions = answering_dimensions(value, questions)
        pool.append(
            {
                "text": value,
                "dimensions": sorted(dimensions),
                "position": index,
            }
        )
    # Prefer a sentence that answers an actual research question, then keep the
    # reading order of the page.
    pool.sort(key=lambda row: (not row["dimensions"], row["position"]))
    return pool[: max(1, int(limit))]
