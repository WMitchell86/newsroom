"""Editorial Readiness Layer (M2R): is there a story, is there enough evidence,
why should the reader care?

Sits between research/evidence (frozen M2.3B) and drafting. Composes three
inspectable contracts on top of the existing editorial-value gate:

* evidence sufficiency - semantic information coverage per dimension, MODE-aware
  guidance patterns (not hard field-count rules, never a word-count rule);
* reader-interest planning - the strongest TRUTHFUL reason to care (hook),
  strategy chosen per evidence and MODE; serious subjects never get playful
  framing; hook factual premises stay inside the normal factual gate;
* article readiness - one orchestrator state (DRAFT_READY / RESEARCH_MORE /
  NO_PUBLISHABLE_ANGLE / EDITOR_DECISION_REQUIRED) combining newsworthiness,
  sufficiency and research-gap status.

Factual-gate status is independent and untouched (a fully grounded draft can
still be editorially inadequate - §14). Targeted research is gap-driven: the
planner names missing semantics and concrete research questions; it never
hardcodes sources or websites (§12). Good Enough binds: max 2 targeted
enrichment rounds after initial research (§13).
"""

from __future__ import annotations

import re
from copy import deepcopy

from editor_assistant.workflow import angles as angles_mod
from editor_assistant.workflow import modes as modes_mod

# ---------- statuses ----------
DRAFT_READY = "DRAFT_READY"
RESEARCH_MORE = "RESEARCH_MORE"
NO_ANGLE = angles_mod.NO_ANGLE  # NO_PUBLISHABLE_ANGLE
EDITOR_DECISION = "EDITOR_DECISION_REQUIRED"

SUFFICIENT = "EVIDENCE_SUFFICIENT"
INSUFFICIENT = "INSUFFICIENT_FOR_ARTICLE"
SUFFICIENCY_STATUSES = (SUFFICIENT, RESEARCH_MORE, INSUFFICIENT, EDITOR_DECISION)

HOOK_STRATEGIES = (
    "STRONGEST_FACT",
    "CONSEQUENCE",
    "SCALE",
    "LOCAL_IMPACT",
    "HUMAN_INTEREST",
    "CURIOSITY",
    "UNUSUAL_DETAIL",
    "PRACTICAL_VALUE",
    "PLAYFUL",
)
MAX_RESEARCH_ROUNDS = 2

MODES = ("MODE_STANDARD_NEWS", "MODE_BRIEF", "MODE_EVENT_PREVIEW", "MODE_CULTURE_FEATURE")


class ReadinessError(ValueError):
    pass


# ---------- semantic surface detection ----------
# Stem-based BG patterns (suffix-tolerant: "входът" must match "вход"), plus a
# few EN equivalents. These are generic semantic cues, not entity rules.

_CUE = {
    # A. core proposition / verification context
    "event_schedule": re.compile(
        r"\b\d{1,2}[:.]\d{2}\s*ч\b|\bпрограм\w*|\bзапочва\b|\bпродължава\b|"
        r"\bоткриване\b|\bзакриване\b|\bкрая\b|\bschedule\b|\bstart(?:s|ing)?\b",
        re.IGNORECASE,
    ),
    "admission": re.compile(
        r"\bбезплатен\w*|\bбез вход\b|\bвход\w*|\bбилет\w*|\bцена\b|"
        r"\badmission\b|\bticket\w*",
        re.IGNORECASE,
    ),
    "participants": re.compile(
        r"\bучастник\w*|\bучаств\w*|\bвключва\b|\bгост\w*|"
        r"\bизпълнител\w*|\bcast\b",
        re.IGNORECASE,
    ),
    "venue": re.compile(
        r"\bзал\w*|\bдомина\b|\bдом\b|\bцентър\w*|\bплощад\b|\bгалери\w*|"
        r"\bмузей\b|\bбиблиотек\w*|\bтеатър\w*|\bvenue\b",
        re.IGNORECASE,
    ),
    "amount": re.compile(
        r"\bлева\b|\bевро\b|\bмлн\b|\bмлрд\b|\bхил\b|\bсумата?\b|"
        r"\bфинансиран\w*|\bbudget\b|\bfunding\b",
        re.IGNORECASE,
    ),
    "recipients": re.compile(
        r"\bфизически лица\b|\bполучател\w*|\bбенефициент\w*|"
        r"\bсемейства\b|\bученици\b|\bпенсионер\w*",
        re.IGNORECASE,
    ),
    "decision_status": re.compile(
        r"\bприе\b|\bприет\w*|\bодобри\b|\bодобрен\w*|"
        r"\bотхвърли\b|\bотхвърлен\w*|\bгласува\b|\bподкрепи\b|"
        r"\bрешени[ея]\b|\bпротокол\b|\badopted\b|\bapproved\b",
        re.IGNORECASE,
    ),
    "authority": re.compile(
        r"\bкмет\w*|\bобщин\w*|\bдиректор\w*|\bминистър\w*|"
        r"\bпресцентър\w*|\bорганизатор\w*|\bкомиси\w*|\bфондаци\w*|"
        r"\bагенция\b|\bpress\b|\bspokesperson\b",
        re.IGNORECASE,
    ),
    # C. reader-value context
    "who_affected": re.compile(
        r"\bграждан\w+|\bжител\w+|\bдец[аа]\b|\bученици\b|"
        r"\bсемейства\b|\bпенсионер\w*|\bпотребител\w*|"
        r"\bпострадал\w*|\bнаранен\w*|\bфизически лица\b",
        re.IGNORECASE,
    ),
    "why_it_matters": re.compile(
        r"\bзасяга\b|\bзначение\b|\bважно\b|\bпърви\b|\bвпърви\b|"
        r"\bнай-голям\w*|\bслед\s+\d+\s+години\b",
        re.IGNORECASE,
    ),
    "consequence": re.compile(
        r"\bще даде\b|\bще позволи\b|\bще осигури\b|\bрезултат\w*|"
        r"\bефект\w*|\bвъздействи\w*|\bconsequence\b",
        re.IGNORECASE,
    ),
    "scale": re.compile(
        r"\b\d+-?(?:о|ото|и|ти)\s+издание\b|\bдевет(?:о|ото)\b|"
        r"\b\d+\s*(?:участници|филма|титули|деца|души|концерта)\b",
        re.IGNORECASE,
    ),
    "quote": re.compile(r"[«\"„][^»\"“]{3,}[»\"“]"),
    "practical": re.compile(
        r"\bвход\w*|\bбилет\w*|\bзаписване\b|\bадрес\b|\bчас\w*|"
        r"\bсвободен\b|\bбезплатен\w*",
        re.IGNORECASE,
    ),
    "background": re.compile(
        r"\bпрез\s+20\d\d\s*г\b|\bистори\w*|\bтрадиционн\w*|\bпреди\b", re.IGNORECASE
    ),
    "unusual": re.compile(
        r"\bза пръв път\b|\bвпърви\b|\bнеобичайн\w*|\bрекорд\b|"
        r"\bнов\w+\s+елемент\b|\bновинката\b",
        re.IGNORECASE,
    ),
    "whats_next": re.compile(
        r"\bследващ[ао]\w*|\bоттук нататък\b|\bще продължи\b|"
        r"\bочаква се\b",
        re.IGNORECASE,
    ),
    "when_where": re.compile(r".", re.IGNORECASE),  # structural: set from dates/places below
    "program": re.compile(r"\bпрограм\w*", re.IGNORECASE),
    "format": re.compile(
        r"\bформат\w*|\bконкурс\w*|\bрегламент\b|\bкатегори\w*|\bformat\b", re.IGNORECASE
    ),
}

# MODE guidance patterns (§9): which dimensions count as reader-value DEPTH
# beyond the bare announcement for this story type. Guidance, not templates:
# one present depth dimension is enough for a good-enough draft; the full
# missing list is reported as optional enrichment gaps.
MODE_GUIDANCE = {
    "MODE_STANDARD_NEWS": {
        "depth": (
            "who_affected",
            "why_it_matters",
            "consequence",
            "scale",
            "authority",
            "when_where",
            "amount",
        ),
    },
    # BRIEF must not become an escape hatch: even a short item needs time/place
    # or affected-people depth, never just an announcement formula.
    "MODE_BRIEF": {
        "depth": ("when_where", "who_affected"),
    },
    "MODE_EVENT_PREVIEW": {
        "depth": (
            "event_schedule",
            "participants",
            "program",
            "admission",
            "format",
            "practical",
            "unusual",
        ),
    },
    "MODE_CULTURE_FEATURE": {
        "depth": (
            "event_schedule",
            "participants",
            "program",
            "quote",
            "background",
            "scale",
            "unusual",
        ),
    },
}

# Generic reader-value vocabulary (layer C, §8): ANY one of these beyond the
# bare announcement makes the surface more than an announcement. A story with
# none of them is a bare announcement - RESEARCH_MORE in every MODE, so BRIEF
# can never be used to bypass the research requirement (§27/Fixture C).
GENERIC_DEPTH = (
    "who_affected",
    "why_it_matters",
    "consequence",
    "scale",
    "quote",
    "practical",
    "background",
    "unusual",
    "whats_next",
    "participants",
    "program",
    "format",
    "admission",
    "amount",
    "recipients",
)

# Hook strategy fit (§15-16): evidence dimensions that support each strategy.
HOOK_FIT = {
    "STRONGEST_FACT": ("decision_status", "amount", "authority"),
    "CONSEQUENCE": ("consequence", "why_it_matters"),
    "SCALE": ("scale",),
    "LOCAL_IMPACT": ("who_affected", "consequence"),
    "HUMAN_INTEREST": ("who_affected", "participants"),
    "CURIOSITY": ("unusual", "quote"),
    "UNUSUAL_DETAIL": ("unusual", "scale"),
    "PRACTICAL_VALUE": ("practical", "admission", "event_schedule"),
    "PLAYFUL": ("unusual",),
}

# §17 serious subjects: playful/curiosity framing is never selected for these.
SERIOUS_CUES = re.compile(
    r"\bсмърт\b|\bзагина\w*|\bзагуба\b|\bпогребение\b|\bубийство\b|\bпрестъплени\w*|"
    r"\bкриминал\w*|\bпроизшестви\w+|\bкатастрофа\b|\bинцидент\w*|"
    r"\bздравн\w+\s+(?:криза|извънредн\w*)\b|\bепидеми\w+|\bвирус\b|"
    r"\bсъд\w*|\bдело\b|\bобвинени\w*|\bнепълнолет\w+|\bтрагеди\w*|\bжертв\w+",
    re.IGNORECASE,
)

# §18 entertainment energy: playful framing needs BOTH a suitable subject AND
# a supported comic/unusual premise in evidence - never subject alone.
PLAYFUL_CUES = re.compile(
    r"\bкомеди\w*|\bсатир\w*|\bспектакъл\b|\bконцерт\b|\bфестивал\b|\bкарнавал\b|"
    r"\bпразник\b|\bзабавен\b|\bхумор\b|\bшоу\b",
    re.IGNORECASE,
)
COMEDY_PREMISE_CUES = re.compile(
    r"\bкомеди\w+|\bнеканени гости\b|\bлъжи\b|\bобърканост\b|\bзабъркан\w*|"
    r"\bфарс\b|\bсмешн\w+",
    re.IGNORECASE,
)


def _has_dim(text, dim):
    return dim in _CUE and bool(_CUE[dim].search(text))


def _detect_dimensions(packet, extra_text=""):
    """Which semantic dimensions the evidence surface actually shows."""
    parts = [f["text"] for f in packet.get("facts", [])]
    parts.append(str(packet.get("source_headline", "") or ""))
    if extra_text:
        parts.append(extra_text)
    for q in packet.get("quotes", []):
        parts.append(str(q.get("text", "")))
    for key in ("dates", "places"):
        vals = packet.get(key) or []
        if vals:
            parts.append(" ".join(str(x) for x in vals))
    text = "\n".join(parts)
    present = {dim for dim in _CUE if dim != "when_where" and _CUE[dim].search(text)}
    if packet.get("dates") or packet.get("places"):
        present.add("when_where")
    if packet.get("facts"):
        present.add("core_proposition")
    return present


def _gap_questions(missing):
    """Gap-driven, semantic research questions - never source-specific (§12)."""
    labels = {
        "event_schedule": "Кога точно (часове, дати) и каква е програмата?",
        "admission": "Свободен ли е входът или е с билети, и на каква цена?",
        "participants": "Кои са участниците/изпълнителите/гостите?",
        "venue": "Къде точно ще се състои събитието?",
        "amount": "Каква е сумата/финансирането и за какво точно?",
        "recipients": "Кои са получателите и по какви условия?",
        "decision_status": "Какво точно е решено и дали решението е фактически взето?",
        "authority": "Кой орган/отговорник е източникът на информацията?",
        "when_where": "Кога и къде?",
        "who_affected": "Кои хора са засегнати и как?",
        "why_it_matters": "Защо това има значение за читателя тук и сега?",
        "consequence": "Каква е практическата последица за читателя?",
        "scale": "Какъв е обхватът (числа, брой участници/ползватели)?",
        "format": "Какъв е форматът/правилата/категориите?",
        "program": "Каква е програмата?",
        "background": "Какъв е контекстът/предисторията?",
        "quote": "Има ли достъпно цитируемо становище от отговорен участник?",
        "practical": "Каква практическа информация е нужна (вход, адрес, записване)?",
        "unusual": "Има ли отличителен/необичаен елемент този път?",
        "whats_next": "Какво следва след това?",
    }
    return [labels[m] for m in missing if m in labels]


# ---------- Skill B: evidence sufficiency (§7-10) ----------


def assess_sufficiency(packet, *, mode, extra_text=""):
    """MODE-aware semantic information coverage for the intended article.

    Returns {status, present_dimensions, missing_dimensions, research_questions,
    reason, mode}. Semantic coverage only - no word counts, no numeric
    threshold. Outcomes (§10): EVIDENCE_SUFFICIENT, RESEARCH_MORE,
    INSUFFICIENT_FOR_ARTICLE, EDITOR_DECISION_REQUIRED (the last is reserved
    for the orchestrator, not produced here).

    Rule (§8): core proposition is mandatory; beyond it a story needs AT LEAST
    SOME reader-value depth from the MODE's guidance list. A bare announcement
    with zero depth stays RESEARCH_MORE - choosing BRIEF does not bypass this.
    """
    if mode not in MODE_GUIDANCE:
        raise ReadinessError(f"unknown mode: {mode!r} (use {MODES})")
    present = _detect_dimensions(packet, extra_text=extra_text)
    depth_dims = MODE_GUIDANCE[mode]["depth"]
    missing = [d for d in depth_dims if d not in present]
    has_depth = bool(set(present) & set(GENERIC_DEPTH))
    if not packet.get("facts"):
        status = "INSUFFICIENT_FOR_ARTICLE"
    elif not has_depth:
        # bare announcement: no reader-value depth at all for ANY story type
        status = RESEARCH_MORE
    elif missing and len(missing) == len(depth_dims):
        # has generic depth, but nothing this story type needs (wrong shape)
        status = RESEARCH_MORE
    else:
        status = SUFFICIENT
    research_questions = _gap_questions(missing)
    if status == SUFFICIENT:
        reason = (
            f"Достатъчно семантично покритие за {mode}: има конкретна новост и "
            f"читателска дълбочина ({', '.join(d for d in depth_dims if d in present)})."
        )
    elif not has_depth:
        reason = (
            f"Гола новина без читателска дълбочина за {mode}: липсват "
            f"{', '.join(missing)}. Нужно е целенасочено проучване по тях."
        )
    elif status == RESEARCH_MORE:
        reason = (
            f"Покритието не отговаря на {mode}: липсват {', '.join(missing)}. "
            "Нужно е целенасочено проучване."
        )
    else:
        reason = "Няма факти - не може да се съди за достатъчност."
    return {
        "status": status,
        "present_dimensions": sorted(present),
        "missing_dimensions": missing,
        "research_questions": research_questions,
        "reason": reason,
        "mode": mode,
        "bare_announcement": not has_depth,
    }


# ---------- Skill D: reader interest / hook (§15-21) ----------


def _serious_subject(text):
    return bool(SERIOUS_CUES.search(text))


def plan_reader_interest(packet, *, mode):
    """Choose the strongest TRUTHFUL reader-interest strategy from evidence.

    Serious subjects (death, crime, accidents, health emergencies, courts,
    minors, tragedy, allegations) never receive playful or curiosity framing
    (§17). A playful strategy exists only for entertainment subjects with a
    supported comic/unusual premise in evidence (§18); every factual premise a
    hook carries remains inside the normal factual gate (§19). The rationale
    names the supporting dimensions so the choice stays inspectable.
    """
    present = _detect_dimensions(packet)
    text = "\n".join(
        [f["text"] for f in packet.get("facts", [])]
        + [str(packet.get("source_headline", "") or "")]
    )
    serious = _serious_subject(text)
    # §18: a supported comic/unusual premise on an entertainment subject counts
    # as an unusual element - it is the distinctive reader-interest surface.
    comedic_premise = not serious and PLAYFUL_CUES.search(text) and COMEDY_PREMISE_CUES.search(text)
    if comedic_premise:
        present.add("unusual")
    ranked = []
    for strategy, dims in HOOK_FIT.items():
        support = [d for d in dims if d in present]
        if not support:
            continue
        weight = len(support) + (
            1 if mode == "MODE_EVENT_PREVIEW" and strategy == "PRACTICAL_VALUE" else 0
        )
        if comedic_premise and strategy in ("PLAYFUL", "CURIOSITY"):
            # §18, §21: the grounded curiosity IS the distinctive angle - a
            # light opening outranks generic/practical lead strategies while
            # staying within the evidence.
            weight += 5
        ranked.append((weight, strategy, support))
    ranked.sort(key=lambda t: (-t[0], t[1]))
    if serious:
        ranked = [c for c in ranked if c[1] in ("STRONGEST_FACT", "CONSEQUENCE", "LOCAL_IMPACT")]
    elif not comedic_premise:
        ranked = [c for c in ranked if c[1] != "PLAYFUL"]
    if ranked:
        _weight, strategy, support = ranked[0]
        rationale = (
            f"Стратегия {strategy}: подкрепена от измерения "
            f"{', '.join(support)}; hook-ът не добавя факти извън тях."
        )
    else:
        strategy = "STRONGEST_FACT"
        support = ["core_proposition"]
        rationale = (
            "Няма специфични читателски измерения; hook-ът остава чисто "
            "констативен - най-силният подкрепен факт."
        )
    basis = _basis_fact_ids(packet, support)
    return {
        "hook_strategy": strategy,
        "basis_fact_ids": basis,
        "rationale": rationale,
        "serious_subject": serious,
        "alternatives_considered": [c[1] for c in ranked[1:4]],
    }


def _basis_fact_ids(packet, support_dims):
    """Facts carrying the hook's supporting dimensions (traceable basis, §19)."""
    dims_rx = [_CUE[d] for d in support_dims if d in _CUE]
    out = [f["id"] for f in packet.get("facts", []) if any(rx.search(f["text"]) for rx in dims_rx)]
    return out or [f["id"] for f in packet.get("facts", [])[:1]]


# ---------- orchestration (§24, §26, §31) ----------


def _surface_semantic_status(packet, fact_ids):
    """Semantic viability from the raw evidence surface (no judgment supplied).

    VIABLE only when the supporting facts express a concrete new event/change
    (novelty cue). This is the same floor the angle gate enforces; sufficiency
    then decides whether the surface is rich enough.
    """
    facts = packet.get("facts", [])
    wanted = set(fact_ids) if fact_ids else {f["id"] for f in facts}
    if any(angles_mod.NOVELTY_CUE.search(f["text"]) for f in facts if f["id"] in wanted):
        return angles_mod.VIABLE
    return angles_mod.NOT_VIABLE


def readiness_for_candidate(packet, candidate, *, mode, sufficiency=None):
    """Compose one candidate's inspectable readiness record (§31 shape)."""
    if sufficiency is None:
        sufficiency = assess_sufficiency(packet, mode=mode)
    interest = plan_reader_interest(packet, mode=mode)
    semantic_status = candidate.get("semantic_status")
    if semantic_status is None:
        semantic_status = _surface_semantic_status(packet, candidate.get("fact_ids", []))
    if semantic_status == angles_mod.NOT_VIABLE:
        overall = NO_ANGLE
        reason = "Няма конкретна подкрепена новост - кандидатът не може да стане статия."
    elif semantic_status == angles_mod.NEEDS_RESEARCH:
        overall = RESEARCH_MORE
        reason = "Има потенциал, но липсват ключови факти - нужно е целенасочено проучване."
    elif sufficiency["status"] == SUFFICIENT:
        overall = DRAFT_READY
        reason = "Подкрепена новост + достатъчно семантично покритие; готово за чернова."
    elif sufficiency["status"] == RESEARCH_MORE:
        overall = RESEARCH_MORE
        reason = "Има новост, но повърхността е гола новина за замисления MODE."
    else:
        overall = EDITOR_DECISION
        reason = "Доказателствената повърхност не позволява автоматично решение."
    angle_summary = str(candidate.get("title", ""))
    if candidate.get("new_proposition"):
        angle_summary = f"{angle_summary} — {candidate['new_proposition']}"
    return {
        "angle_id": candidate.get("angle_id"),
        "angle_summary": angle_summary,
        "supporting_fact_ids": list(candidate.get("fact_ids", [])),
        "newsworthiness": {
            "semantic_status": semantic_status,
            "rationale": str(candidate.get("reason", "")),
            "diagnostic_scores": {
                "total": candidate.get("total", 0),
                "threshold": angles_mod.THRESHOLD,
            },
        },
        "sufficiency": sufficiency,
        "reader_interest": {**interest, "hook_note": interest["rationale"]},
        "article_readiness": {"status": overall, "reason": reason},
    }


def assess_readiness(packet, *, mode=None, candidate=None):
    """One overall state before drafting (§24).

    Combines the (recomputed) editorial-value gate with evidence sufficiency
    and a reader-interest plan. Numerical rubric totals rank and diagnose only
    (§26); semantic viability + sufficiency decide. Without a stored assessment
    and a supplied candidate, transcript/council packets raise
    ANGLE_REVIEW_REQUIRED; other packets are judged on the raw evidence surface
    (never auto-eligible by score alone).
    """
    if mode is None:
        mode = modes_mod.suggest_mode(packet)["suggested_mode"]
    assessment = angles_mod.check_angle_gate(packet)
    if assessment is None:
        if angles_mod.needs_angle_review(packet):
            raise angles_mod.AngleError(
                "ANGLE_REVIEW_REQUIRED: supply 3-5 assessed research angles via live-angles"
            )
        cand = candidate or {
            "angle_id": "AD-HOC",
            "title": str(packet.get("source_headline", "")),
            "fact_ids": [f["id"] for f in packet.get("facts", [])],
            "scores": {},
            "reason": "Директна оценка на повърхността на доказателствата.",
        }
        rec = readiness_for_candidate(packet, cand, mode=mode)
        return {
            "status": rec["article_readiness"]["status"],
            "mode": mode,
            "reason": rec["article_readiness"]["reason"],
            "editorial_value_status": rec["newsworthiness"]["semantic_status"],
            "evidence_sufficiency_status": rec["sufficiency"]["status"],
            "hook_strategy": rec["reader_interest"]["hook_strategy"],
            "reader_interest": rec["reader_interest"],
            "sufficiency": rec["sufficiency"],
            "candidate": rec,
            "assessment": None,
        }
    if assessment["status"] == angles_mod.NO_ANGLE:
        return {
            "status": NO_ANGLE,
            "mode": mode,
            "reason": assessment["reason"],
            "editorial_value_status": angles_mod.NOT_VIABLE,
            "evidence_sufficiency_status": None,
            "hook_strategy": None,
            "candidate": None,
            "assessment": assessment,
        }
    if assessment["status"] == angles_mod.NEEDS_RESEARCH:
        return {
            "status": RESEARCH_MORE,
            "mode": mode,
            "reason": assessment["reason"],
            "editorial_value_status": angles_mod.NEEDS_RESEARCH,
            "evidence_sufficiency_status": None,
            "hook_strategy": None,
            "candidate": None,
            "assessment": assessment,
        }
    # ANGLE_SELECTED: scope to the angle, then judge sufficiency on the scope.
    selected = next(
        c for c in assessment["candidates"] if c["angle_id"] == assessment["selected_angle_id"]
    )
    scoped = angles_mod.selected_angle_packet(packet, assessment)
    sufficiency = assess_sufficiency(scoped, mode=mode)
    hook = plan_reader_interest(scoped, mode=mode)
    if sufficiency["status"] == SUFFICIENT:
        overall = DRAFT_READY
        reason = "Избран ъгъл + достатъчно покритие за MODE; черновата може да тръгне."
    elif sufficiency["status"] == RESEARCH_MORE:
        overall, reason = RESEARCH_MORE, sufficiency["reason"]
    else:
        overall, reason = EDITOR_DECISION, sufficiency["reason"]
    rec = readiness_for_candidate(scoped, selected, mode=mode, sufficiency=sufficiency)
    return {
        "status": overall,
        "mode": mode,
        "reason": reason,
        "editorial_value_status": angles_mod.VIABLE,
        "evidence_sufficiency_status": sufficiency["status"],
        "hook_strategy": hook["hook_strategy"],
        "reader_interest": hook,
        "sufficiency": sufficiency,
        "candidate": rec,
        "assessment": assessment,
    }


# ---------- hook -> prompt task_extra (§19-21) ----------

_CLICKBAIT = re.compile(
    r"Няма да повярвате|Ето какво|Шок|Скандал|Невероятно|Не можете да пропуснете", re.IGNORECASE
)


def hook_task_extra(hook):
    """Reader-interest instruction fragment for the drafting prompt (§15-21).

    Grounded by construction: names the strategy, restricts its factual basis
    to basis_fact_ids (every proposition stays inside the normal factual
    gate), and states the serious-subject tone rule. Never asks for new facts.
    """
    strategy = hook["hook_strategy"]
    basis = ", ".join(hook.get("basis_fact_ids", [])) or "(няма - само констатация)"
    lines = [" РЕДАКТОРСКИ ПЛАН ЗА ИНТЕРЕС (M2R): "]
    if hook.get("serious_subject"):
        lines.append(
            "Темата е сериозна - тон: сдържан, фактологичен; без игривост, сензационност "
            "или емоционална манипулация. "
        )
    lines.append(
        f"Хук стратегия: {strategy}. Фактуална основа само от фактове: {basis}; "
        "hook-ът не въвежда нови факти, реакции или оценки извън CURRENT EVIDENCE. "
    )
    lines.append(
        "Отворете със силния нов факт / последицата / практическата полза, не с "
        "институционална формула, освен ако тя не е най-ясният новинарски водач. "
    )
    lines.append(
        "Предложете до 3 заглавия с различен истински акцент (директно фактическо; "
        "най-силният читателски ъгъл; по-енергично в рамките на тона на сайта). "
        "Забранени са кликбейт-заглавия - прочетете списъка със забранени шаблони "
        "в editorial_readiness_guidance.json и не ги използвайте в нито една форма."
    )
    text = "".join(lines)
    if _CLICKBAIT.search(text):  # guard our own instruction text (§20)
        raise ReadinessError("hook_task_extra produced a forbidden clickbait pattern")
    return text


# ---------- Skill C: targeted research expansion (§11-13) ----------


def expansion_plan(readiness, *, rounds_used=0):
    """Gap-driven expansion plan from a RESEARCH_MORE readiness result (§11-12).

    Names the missing semantics and concrete research questions; WHERE to look
    (organizer, venue, federation, ticket platform...) is the research layer's
    decision, never encoded here.
    """
    if readiness["status"] != RESEARCH_MORE:
        raise ReadinessError("expansion_plan requires a RESEARCH_MORE readiness result")
    suff = readiness.get("sufficiency") or (readiness.get("candidate") or {}).get("sufficiency", {})
    remaining = MAX_RESEARCH_ROUNDS - rounds_used
    if remaining <= 0:
        return {
            "missing_dimensions": [],
            "research_questions": [],
            "max_rounds_remaining": 0,
            "note": "Достигнат е лимитът от 2 целенасочени проучвателни рунда; "
            "вземете решение: достатъчно / недостатъчно / редакторска намеса.",
        }
    return {
        "missing_dimensions": list(suff.get("missing_dimensions", [])),
        "research_questions": list(suff.get("research_questions", [])),
        "max_rounds_remaining": remaining,
    }


def register_research_round(record, *, missing_dimensions, research_questions, sources=()):
    """Record one targeted enrichment round on the evidence row (§11-13).

    Returns a copy of the record with the round appended. More than
    MAX_RESEARCH_ROUNDS raises - the caller must then choose
    EVIDENCE_SUFFICIENT / INSUFFICIENT_FOR_ARTICLE / EDITOR_DECISION_REQUIRED
    (Good Enough remains binding).
    """
    record = deepcopy(record)
    rounds = int(record.get("targeted_research_rounds", 0))
    if rounds >= MAX_RESEARCH_ROUNDS:
        raise ReadinessError(
            f"targeted research limit reached ({MAX_RESEARCH_ROUNDS} rounds); "
            "decide: sufficient / insufficient / editor decision"
        )
    record["targeted_research_rounds"] = rounds + 1
    record.setdefault("research_rounds", []).append(
        {
            "round": rounds + 1,
            "missing_dimensions": list(missing_dimensions),
            "research_questions": list(research_questions),
            "sources": [dict(s) for s in sources],
        }
    )
    return record


# ---------- editor override (§32) ----------


def apply_editor_override(readiness, *, action, reason):
    """Record an editor override; never silently pretend sufficiency (§32).

    action: FORCE_DRAFT | CHANGE_ANGLE | REQUEST_MORE_RESEARCH | REJECT_STORY.
    FORCE_DRAFT keeps the original state visible in `pre_override_status` and
    marks `editor_override`, so lineage shows drafting started from weak
    evidence on an explicit editor decision.
    """
    actions = ("FORCE_DRAFT", "CHANGE_ANGLE", "REQUEST_MORE_RESEARCH", "REJECT_STORY")
    if action not in actions:
        raise ReadinessError(f"bad editor override action: {action!r} (use {actions})")
    if not isinstance(reason, str) or not reason.strip():
        raise ReadinessError("editor override requires a recorded reason")
    out = deepcopy(readiness)
    out["pre_override_status"] = out.get("pre_override_status", out.get("status"))
    if action == "FORCE_DRAFT":
        out["status"] = DRAFT_READY
    out["editor_override"] = {"action": action, "reason": reason.strip()}
    return out
