"""M2.9 deterministic draft->final diff + revision classification (stdlib only).

Deterministic diff first (headline, paragraph added/removed/reordered,
sentence added/removed). Classification separates FACT from STYLE: a changed
number in a matched sentence pair is FACT, never a style preference.
LLM-assisted classification may be layered on top later, but it must never
modify the stored final text.
"""

from __future__ import annotations

import difflib
import re

from editor_assistant.drafting.evidence import _sentences

CATEGORIES = (
    "FACT",
    "STYLE",
    "STRUCTURE",
    "TONE",
    "HEADLINE",
    "LOCAL_TERMINOLOGY",
    "FORMAT",
    "OTHER",
)
_NUMBER = re.compile(r"\d[\d.,:\s]*")
_WORD = re.compile(r"[\w\-]+")


def split_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _norm(t):
    return re.sub(r"\s+", " ", (t or "").strip())


def diff_draft_final(draft_headline, draft_text, final_headline, final_text):
    """Deterministic structural diff between the AI draft and the editor final."""
    d_paras = split_paragraphs(draft_text)
    f_paras = split_paragraphs(final_text)
    d_norm = [_norm(p) for p in d_paras]
    f_norm = [_norm(p) for p in f_paras]
    sm = difflib.SequenceMatcher(a=d_norm, b=f_norm, autojunk=False)
    added, removed = [], []
    reordered = False
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(f_paras[j1:j2])
        if tag in ("delete", "replace"):
            removed.extend(d_paras[i1:i2])
    # reorder: same multiset of paragraphs, different order (independent of how
    # difflib renders the edit — a swap may appear as replace or delete+insert)
    reordered = len(d_norm) == len(f_norm) and sorted(d_norm) == sorted(f_norm) and d_norm != f_norm
    d_sents = [s for p in d_paras for s in _sentences(p)]
    f_sents = [s for p in f_paras for s in _sentences(p)]
    ssm = difflib.SequenceMatcher(
        a=[_norm(s) for s in d_sents], b=[_norm(s) for s in f_sents], autojunk=False
    )
    sent_added = [
        f_sents[j]
        for tag, _i1, _i2, j1, j2 in ssm.get_opcodes()
        for j in range(j1, j2)
        if tag in ("insert", "replace")
    ]
    sent_removed = [
        d_sents[i]
        for tag, i1, i2, _j1, _j2 in ssm.get_opcodes()
        for i in range(i1, i2)
        if tag in ("delete", "replace")
    ]
    return {
        "headline_changed": _norm(draft_headline) != _norm(final_headline),
        "paragraphs": {"added": added, "removed": removed, "reordered": reordered},
        "sentences": {
            "added_count": len(sent_added),
            "removed_count": len(sent_removed),
            "added": sent_added[:6],
            "removed": sent_removed[:6],
        },
        "word_delta": len(_WORD.findall(final_text or "")) - len(_WORD.findall(draft_text or "")),
        "paragraph_count_draft": len(d_paras),
        "paragraph_count_final": len(f_paras),
    }


def classify_diff(diff):
    """Deterministic first-pass correction categories from the diff.

    FACT beats STYLE: if a matched sentence pair differs only (or chiefly) in
    numbers, the correction is factual. Paragraph-level adds/removes/moves are
    STRUCTURE. Headline rewrite is HEADLINE.
    """
    counts = {c: 0 for c in CATEGORIES}
    examples = {c: [] for c in CATEGORIES}

    def _bump(cat, example):
        counts[cat] += 1
        if len(examples[cat]) < 5:
            examples[cat].append(example[:200])

    if diff["headline_changed"]:
        _bump("HEADLINE", "headline rewritten")
    if (
        diff["paragraphs"]["added"]
        or diff["paragraphs"]["removed"]
        or diff["paragraphs"]["reordered"]
    ):
        _bump("STRUCTURE", "paragraph added/removed/reordered")
    removed_norm = {_norm(s) for s in diff["sentences"]["removed"]}
    for sent in diff["sentences"]["added"]:
        s_norm = _norm(sent)
        # nearest removed sentence by token overlap
        best, best_ratio = None, 0.0
        for cand in removed_norm:
            ratio = difflib.SequenceMatcher(a=s_norm, b=cand).ratio()
            if ratio > best_ratio:
                best, best_ratio = cand, ratio
        if best is not None and best_ratio >= 0.5:
            nums_a = set(_NUMBER.findall(s_norm))
            nums_r = set(_NUMBER.findall(best))
            if nums_a != nums_r:
                _bump("FACT", f"number changed: {sorted(nums_a ^ nums_r)}")
            else:
                _bump("STYLE", f"reworded: {best[:80]}")
            removed_norm.discard(best)
        else:
            _bump("STRUCTURE", f"sentence added: {s_norm[:80]}")
    for sent in list(removed_norm):
        _bump("STRUCTURE", f"sentence removed: {sent[:80]}")
    if (
        counts["HEADLINE"] == 0
        and counts["FACT"] == 0
        and counts["STRUCTURE"] == 0
        and counts["STYLE"] == 0
        and counts["TONE"] == 0
    ):
        _bump("OTHER", "no material change detected")
    return {
        "counts": counts,
        "examples": examples,
        "dominant": max(counts, key=lambda c: counts[c]),
    }
