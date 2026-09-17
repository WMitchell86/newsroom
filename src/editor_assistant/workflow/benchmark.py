"""M2.7-9 Track A benchmark: AI draft vs the actually-published article.

GROUND_TRUTH_DRYRUN measurement only. For every dry-run case we compare the
grounded AI draft against the published article that the newsroom wrote from
the same source: deterministic structural similarity (paragraph order via
SequenceMatcher, headline token overlap) plus the frozen M2.3B factual audit
(lexical + semantic). No effort/adoption numbers ever come from here.
"""

from __future__ import annotations

import difflib
import json
import re

from editor_assistant.workflow.cases import read_cases
from editor_assistant.workflow.diff import diff_draft_final

_WORD = re.compile(r"[\w\-]+", re.UNICODE)


def _token_set(text):
    return {t.lower() for t in _WORD.findall(text or "")}


def _token_overlap(a, b):
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def structural_similarity(draft_text, published_text):
    """0..1 order-aware similarity of the two paragraph sequences."""
    d = [
        re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", draft_text or "") if p.strip()
    ]
    p = [
        re.sub(r"\s+", " ", q).strip()
        for q in re.split(r"\n\s*\n", published_text or "")
        if q.strip()
    ]
    if not d or not p:
        return 0.0
    return difflib.SequenceMatcher(a=d, b=p, autojunk=False).ratio()


def benchmark_case(case, published_headline, published_text):
    """Deterministic Track-A comparison for one dry-run case."""
    diff = diff_draft_final(
        case["draft_headline"], case["draft_text"], published_headline, published_text
    )
    audit = case.get("audit") or {}
    semantic = audit.get("semantic") or {}
    lex = (
        (audit.get("lexical") or {}).get("primary")
        if isinstance(audit.get("lexical"), dict)
        else None
    )
    unsupported = [c for c in semantic.get("claims", []) if c.get("verdict") == "UNSUPPORTED"]
    return {
        "case_id": case["case_id"],
        "evidence_id": case["evidence_id"],
        "headline_overlap": round(_token_overlap(case["draft_headline"], published_headline), 3),
        "headline_changed_vs_published": diff["headline_changed"],
        "structural_similarity": round(
            structural_similarity(case["draft_text"], published_text), 3
        ),
        "word_delta_vs_published": diff["word_delta"],
        "paragraphs": diff["paragraphs"],
        "factual": {
            "lexical_pass": bool(lex)
            and all(
                s.get("verdict") == "SUPPORTED"
                for block in (lex or [])
                for s in (block.get("sentences") or [])
            )
            if lex is not None
            else None,
            "semantic_pass": semantic.get("pass"),
            "semantic_claims": len(semantic.get("claims", [])),
            "unsupported_claims": len(unsupported),
        },
    }


def benchmark_report(cases_path):
    """Aggregate Track-A metrics over all dry-run cases with a published match.

    Editor supplies `published_headline` / `published_text` per case (the
    actually-published article); cases without them are reported as pending.
    """
    rows, pending = [], []
    for case in read_cases(cases_path):
        if case.get("track") != "GROUND_TRUTH_DRYRUN":
            continue
        if case.get("published_headline") and case.get("published_text"):
            rows.append(benchmark_case(case, case["published_headline"], case["published_text"]))
        else:
            pending.append(case["case_id"])
    measured = rows or []
    summary = {
        "track": "GROUND_TRUTH_DRYRUN",
        "cases": len(rows) + len(pending),
        "measured": len(rows),
        "pending_published": pending,
        "mean_structural_similarity": round(
            sum(r["structural_similarity"] for r in measured) / len(measured), 3
        )
        if measured
        else None,
        "mean_headline_overlap": round(
            sum(r["headline_overlap"] for r in measured) / len(measured), 3
        )
        if measured
        else None,
        "headline_kept_vs_published": sum(
            1 for r in measured if not r["headline_changed_vs_published"]
        ),
        "semantic_unsupported_total": sum(r["factual"]["unsupported_claims"] for r in measured),
        "note": "benchmark only - never a source of time/weight/adoption metrics",
    }
    return {"summary": summary, "cases": rows}


def load_published_supply(path):
    """Optional editor-supplied published articles: {evidence_id: {headline, text}}."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        k: {"published_headline": v["headline"], "published_text": v["text"]}
        for k, v in data.items()
    }
