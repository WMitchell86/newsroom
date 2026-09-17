"""M2.3 (and M2.3B corrective) draft prompt builder - versioned, sectioned, stdlib only."""

from __future__ import annotations

import re

PROMPT_VERSION = "m2.3b-prompt-2"
SECTIONS = (
    "SYSTEM",
    "CURRENT_EVIDENCE",
    "CURRENT_QUOTES",
    "CURRENT_UNKNOWNS",
    "SITE_DNA",
    "VOICE_PROFILE",
    "MODE_PROFILE",
    "STYLE_EXAMPLES",
    "TASK",
    "FORBIDDEN",
)


# Concrete institutional-attribution formulas found in style-rule examples. They are
# ARCHIVE/STYLE artifacts: the model must never turn them into facts about the current
# story. Abstract them to a source-anchored instruction instead.
_CONCRETE_ATTRIB = [
    r"съобщиха[^»«\"]{0,60}пресцентъра[^»«\"]{0,60}",
    r"съобщават[^»«\"]{0,40}пресцентъра",
    r"пресцентъра на (?:Областната? )?дирекция на МВР[^»«\".,]*",
    r"ОД на МВР в Бургас",
    r"пресцентъра на ОД на МВР",
    r"съобщават от НИМХ",
    r"от пресцентъра на (?:МВР|ОДМВР|Областна дирекция)",
    r"съобщиха от пресцентъра",
]
_ABSTRACT_ATTRIB = "attribute any source line to the EXACT institution CURRENT EVIDENCE names (and only if CURRENT EVIDENCE names one)"
_CONCRETE_ATTRIB_RE = re.compile("|".join(_CONCRETE_ATTRIB), re.IGNORECASE)


def _sanitize_style_rule(text):
    """Neutralize concrete institution-attribution formulas inside style rules so a
    factual-looking style example (e.g. 'пресцентъра на ОДМВР Бургас') cannot leak
    into a draft as an invented fact. Keeps style as tendency, anchors facts to evidence."""
    if not text:
        return ""
    return _CONCRETE_ATTRIB_RE.sub(_ABSTRACT_ATTRIB, text)


def _profile_text(profile):
    lines = [
        f"# {profile['profile_id']} - {profile.get('display_name', '')}",
        f"Scope: {profile.get('scope', '')}",
        f"Use: {profile.get('preferred_use', '')}",
        f"Headline: {'; '.join(profile['headline']['common_patterns'])}",
        f"Opening: {'; '.join(profile['opening']['typical_patterns'])}",
        f"Body: {profile['body']['paragraph_shape']} {profile['body']['sentence_shape']}",
        f"Quotes: {profile['quotes']['frequency']} {profile['quotes']['placement']}",
        f"Tone: {profile['tone']['factual_vs_descriptive']} {profile['tone']['narrative_distance']}",
        f"Numbers/dates: {'; '.join(profile['numbers_dates']['conventions'])}",
        f"Lexicon tendencies: {'; '.join(profile['lexical_notes']['recurring_preferences'])}",
        f"Avoid tendencies: {'; '.join(profile['avoidances'])}",
        "Style language: tendencies (often/typically/prefer), never mechanical rules.",
    ]
    return _sanitize_style_rule("\n".join(lines))


def _example_text(record):
    paras = [p for p in (record.get("body") or "").split("\n\n") if p.strip()]
    mid = ("\n\n[...]\n\n" + paras[len(paras) // 2][:600]) if len(paras) > 3 else ""
    return (
        f"## STYLE EXAMPLE (style only, NOT facts)\nheadline: {record.get('headline')}\n"
        + f"meta: {record.get('author')} | {record.get('category')} | {record.get('published_date')} | {record.get('url')}\n"
        + f"P1: {(paras[0][:700] if paras else '')}\n"
        + (f"MID: {mid[:700]}\n" if mid else "")
        + f"LAST: {(paras[-1][:400] if paras else '')}"
    )


def build_prompt(packet, *, site_dna, voice_profile, mode_profile, style_examples, task_extra=""):
    mode_id = mode_profile.get("profile_id", "")
    facts = "\n".join(
        f"- [{f['id']}] ({f.get('scope', 'current_event')}) {f['text']}"
        for f in packet.get("facts", [])
    )
    quotes = (
        "\n".join(
            f'- "{q["text"]}" - {q.get("speaker") or "unsourced"} ({q.get("role") or "no role"})'
            for q in packet.get("quotes", [])
        )
        or "(none in evidence - do not invent any)"
    )
    unknowns = "\n".join(f"- {u}" for u in packet.get("unknowns", [])) or "(none recorded)"
    dna = "\n".join(f"- {k}: {v}" for k, v in site_dna.get("conventions", {}).items())
    examples = "\n\n".join(_example_text(e) for e in style_examples)
    mode_guidance = ""
    if mode_id == "MODE_EVENT_PREVIEW":
        mode_guidance = (
            " This is an EVENT PREVIEW: prioritize the practical, forward-looking facts "
            "in CURRENT EVIDENCE in this order - what, where, when (date and time), "
            "programme, final/closing time, how to attend/participate. Keep background sparse. "
            "EVENT_PREVIEW does not mean dry calendar prose. For CULTURE / COMEDY / "
            "ENTERTAINMENT only, allow one light editorial hook or playful sentence when "
            "consistent with the source tone and a synopsis in CURRENT EVIDENCE. Prefer "
            "HOOK -> what/when/where -> why it may interest the reader -> cast/program/practical info. "
            "If evidence is calendar-only or the tone is not playful, omit the hook. "
            "Do not invent plot points, reactions, reviews or audience response. "
            "No advertising exaggeration, superlatives or promises of enjoyment. "
            "A rhetorical question is not a loophole for unsupported factual premises; "
            "editorial color changes wording, never adds facts."
        )
    elif mode_id == "MODE_BRIEF":
        mode_guidance = (
            " This is a BRIEF: whole story in 1-2 dense paragraphs, single fact + "
            "source attribution, then time/place/person details. Do not inflate to a feature."
        )
    sections = {
        "SYSTEM": (
            "You are an assistant to the editor-in-chief of Chernomorie-bg.com. "
            "Write a Bulgarian news draft grounded ONLY in CURRENT EVIDENCE. "
            "Style profiles are tendencies; do not caricature them or copy concrete "
            "institution names from them. Output JSON only."
        ),
        "CURRENT_EVIDENCE": f"Source: {packet['source_url']}\nSource headline: {packet['source_headline']}\n"
        f"Each fact is tagged (current_event) or (historical_background).\nFacts:\n{facts}",
        "CURRENT_QUOTES": quotes,
        "CURRENT_UNKNOWNS": unknowns,
        "SITE_DNA": dna,
        "VOICE_PROFILE": _profile_text(voice_profile),
        "MODE_PROFILE": _profile_text(mode_profile) + mode_guidance,
        "STYLE_EXAMPLES": examples
        + "\n\nStyle examples above are STYLE ONLY. Their people/numbers/dates/quotes/places/institutions must not enter the draft.",
        "TASK": (
            "Write a Bulgarian draft from CURRENT EVIDENCE only, in the given VOICE+MODE tendencies. "
            "Preserve the source's relationships and roles exactly: who does/receives/presents what, "
            "including professor/title bindings (проф., доц.), organization-member links, and the "
            "institution that actually issued the news. "
            'Return STRICT JSON: {"headlines": [up to 3 strings], "headline": str, "body": str (paragraphs separated by blank lines), "attention_notes": str}. '
            + task_extra
        ).strip(),
        "FORBIDDEN": (
            "- facts/people/numbers/dates/quotes/places/institutions from STYLE EXAMPLES or style rules\n"
            "- invented names, roles, dates, numbers, reasons, quotes, causality, institutional positions, or source/institution attributions\n"
            "- re-attributing a statement to an institution CURRENT EVIDENCE does NOT name (e.g. do not say 'пресцентърът на МВР' unless evidence says so)\n"
            "- NEVER transfer a number, participant count, organization, role, date, or relationship from (historical_background) to the current event unless CURRENT EVIDENCE explicitly repeats that link\n"
            "- breaking a professor/title (проф., доц., д-р) binding from the person/play it belongs to in the source\n"
            "- connective facts to smooth prose\n- blockquote/pull-quote layout, subheadline/lead element, first person\n"
            "- anything not supported by CURRENT EVIDENCE (omit unknowns)"
        ),
    }
    text = "\n\n".join(f"===== {name} =====\n{sections[name]}" for name in SECTIONS)
    return {"prompt_version": PROMPT_VERSION, "sections": list(SECTIONS), "text": text}
