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
_FRAGMENT_START = re.compile(
    r"^(?:и|или|но|а|че|да|се|е|са|бе|би|бяха|ще|били|имат|няма)\b", re.IGNORECASE
)
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


def select_candidate_claims(sentences, questions, *, limit: int = 4, topic: str = "") -> list[dict]:
    """A small, ordered candidate set from one opened page (§9, §10).

    At most ``limit`` claims (3-5 by default) are returned, each with the
    dimension it answers, so corroboration compares claims that were extracted
    for the same reason rather than arbitrary sentences. The order is by
    relevance to the Story's questions, and duplicates are dropped.
    """
    pool = []
    seen = set()
    for index, raw in enumerate(sentences or []):
        value = str(raw or "").strip()
        if not value or not is_factual_candidate(value):
            continue
        if not _is_about(value, topic):
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
