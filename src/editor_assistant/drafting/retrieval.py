"""M2.3 style retrieval - lexical/metadata only, stdlib, deterministic.

Ranks the frozen 150-article corpus. VOICE + MODE compatibility first,
then category/story similarity, recent practice, length, topic overlap.
DESISLAVA_RECENT scope lock: legacy Desislava (pre-2024) never returned
for VOICE_DESISLAVA_RECENT. Style examples are STYLE ONLY, never facts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from editor_assistant.style.profiles import ProfileError

VOICE_ALLOW = {
    "VOICE_HOUSE": ("house",),
    "VOICE_DESISLAVA_RECENT": ("desislava_recent",),
}
MODE_PRED = {
    "MODE_STANDARD_NEWS": lambda r: (
        r["author_class"] == "house" and 3 <= r["paras"] <= 5 and (r["date"] or "") >= "2020-01-01"
    ),
    "MODE_BRIEF": lambda r: (
        r["author_class"] == "house" and r["paras"] <= 2 and (r["date"] or "") >= "2020-01-01"
    ),
    "MODE_EVENT_PREVIEW": lambda r: (
        bool(r["event_marker"]) and (r["date"] or "") >= "2024-01-01" and 3 <= r["paras"] <= 8
    ),
    "MODE_CULTURE_FEATURE": lambda r: (
        r["category"] == "\u041a\u0443\u043b\u0442\u0443\u0440\u0430" and r["paras"] >= 6
    ),
}
_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)


class StyleRetrievalError(RuntimeError):
    """Not enough usable style examples — a GENERATION precondition failure.

    Raised by `retrieve_examples_for_generation` BEFORE any model call, so a
    thin corpus can no longer burn one or two model calls and only then fail
    the `exactly 3 style_example_ids` lineage rule (Review G3).
    """


_BG_STOP = frozenset(
    [
        "и",
        "в",
        "на",
        "с",
        "от",
        "за",
        "се",
        "не",
        "по",
        "като",
        "са",
        "ще",
        "то",
        "да",
        "е",
        "ги",
        "го",
        "му",
        "си",
        "й",
        "или",
        "със",
        "през",
        "над",
        "под",
        "във",
        "върху",
        "между",
        "както",
        "само",
        "вече",
        "още",
        "това",
        "тази",
        "този",
        "тези",
        "тя",
        "той",
        "те",
        "те",
        "ни",
        "ви",
        "им",
        "ги",
        "което",
        "която",
        "които",
        "към",
        "до",
        "при",
        "без",
        "около",
        "след",
        "като",
    ]
)


def _tokens(text):
    return [
        w.lower() for w in _WORD_RE.findall(text or "") if len(w) > 2 and w.lower() not in _BG_STOP
    ]


def _topic_overlap(packet_text, article_text):
    a, b = set(_tokens(packet_text)), set(_tokens(article_text))
    if not a or not b:
        return 0.0
    return round(len(a & b) / max(1, min(len(a), len(b))), 3)


def _load_rows(corpus_path, analysis_dir):
    rows = {}
    with open(corpus_path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                paras = [p for p in (r.get("body") or "").split("\n\n") if p.strip()]
                rows[r["article_id"]] = r
    feat = {}
    with open(Path(analysis_dir) / "feature_matrix.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                f = json.loads(line)
                feat[f["article_id"]] = f
    pat = re.compile(
        r"\u0449\u0435 \u0441\u0435 (\u043f\u0440\u043e\u0432\u0435\u0434\u0435|\u0441\u044a\u0441\u0442\u043e\u0438|\u043e\u0440\u0433\u0430\u043d\u0438\u0437\u0438\u0440\u0430)|\u043f\u0440\u0435\u0434\u0441\u0442\u043e\u0438|\u043f\u0440\u043e\u0433\u0440\u0430\u043c\u0430|\u0441\u044a\u0431\u0438\u0442\u0438\u0435\u0442\u043e|\u0444\u0435\u0441\u0442\u0438\u0432\u0430\u043b|\u043a\u043e\u043d\u0446\u0435\u0440\u0442|\u0438\u0437\u043b\u043e\u0436\u0431\u0430|\u043f\u0440\u0435\u043c\u0438\u0435\u0440\u0430|\u043f\u043e\u043a\u0430\u043d\u0435\u043d\u0438|\u0437\u0430\u043f\u043e\u0447\u0432\u0430",
        re.IGNORECASE,
    )
    out = []
    for aid, r in rows.items():
        paras = [p for p in (r.get("body") or "").split("\n\n") if p.strip()]
        author = r.get("author") or ""
        date = r.get("published_date") or ""
        if author == "\u0427\u0435\u0440\u043d\u043e\u043c\u043e\u0440\u0438\u0435-\u0431\u0433":
            vclass = "house"
        elif (
            author
            == "\u0414\u0435\u0441\u0438\u0441\u043b\u0430\u0432\u0430 \u0413\u0435\u043e\u0440\u0433\u0438\u0435\u0432\u0430"
            and date >= "2024-01-01"
        ):
            vclass = "desislava_recent"
        elif (
            author
            == "\u0414\u0435\u0441\u0438\u0441\u043b\u0430\u0432\u0430 \u0413\u0435\u043e\u0440\u0433\u0438\u0435\u0432\u0430"
        ):
            vclass = "desislava_legacy"
        else:
            vclass = "unknown"
        out.append(
            {
                "article_id": aid,
                "author_class": vclass,
                "author": author,
                "category": r.get("category"),
                "date": date,
                "paras": len(paras),
                "chars": len(r.get("body") or ""),
                "url": r.get("url"),
                "headline": r.get("headline"),
                "body": r.get("body") or "",
                "event_marker": bool(pat.search(r.get("body") or "")),
            }
        )
    return out


def score_candidate(row, *, voice, mode, packet):
    if voice not in VOICE_ALLOW:
        raise ProfileError(f"unknown voice: {voice!r}")
    if mode not in MODE_PRED:
        raise ProfileError(f"unknown mode: {mode!r}")
    if row["author_class"] not in VOICE_ALLOW[voice]:
        return None
    mode_ok = bool(MODE_PRED[mode](row))
    parts = {"voice_ok": 1, "mode_ok": int(mode_ok)}
    score = 100.0 + (60.0 if mode_ok else 0.0)
    pcat = (packet.get("category_hint") or "").strip()
    if pcat and row["category"] == pcat:
        score += 25.0
        parts["category"] = 25.0
    year = (row["date"] or "")[:4]
    rec = 20.0 if year >= "2024" else 12.0 if year >= "2020" else 4.0 if year >= "2015" else 0.0
    score += rec
    parts["recency"] = rec
    plen = packet.get("target_chars") or len(packet.get("source_text", ""))
    ldiff = abs(row["chars"] - plen)
    lscore = max(0.0, 15.0 - ldiff / 300.0)
    score += lscore
    parts["length"] = round(lscore, 2)
    tover = _topic_overlap(
        packet.get("source_text", ""), row["headline"] + " " + row["body"][:1500]
    )
    score += tover * 30.0
    parts["topic"] = round(tover * 30.0, 2)
    return round(score, 2), parts


def retrieve_examples(
    packet,
    *,
    voice,
    mode,
    corpus_path,
    analysis_dir,
    top_n=3,
    exclude_ids=(),
    target_chars=None,
    include_body=False,
):
    rows = _load_rows(corpus_path, analysis_dir)
    pkt = dict(packet)
    if target_chars:
        pkt["target_chars"] = target_chars
    scored = []
    for row in rows:
        if row["article_id"] in set(exclude_ids or ()):
            continue
        res = score_candidate(row, voice=voice, mode=mode, packet=pkt)
        if res is None:
            continue
        total, parts = res
        scored.append((total, row["date"], row["article_id"], row, parts))
    scored.sort(
        key=lambda t: (-t[0], -ord((t[1] or " ")[0]) if False else t[1], t[2]), reverse=False
    )
    scored.sort(key=lambda t: (-t[0], t[2]))
    best = scored[:top_n]
    out = []
    for total, _date, _aid, row, parts in best:
        record = {
            "article_id": row["article_id"],
            "url": row["url"],
            "headline": row["headline"],
            "author": row["author"],
            "category": row["category"],
            "published_date": row["date"],
            "score": total,
            "score_parts": parts,
            "why_selected": f"style reference only ({voice}+{mode}); score {total} parts {parts}",
        }
        if include_body:
            # G: prompt-time records carry the prose the drafting prompt
            # actually renders (`prompt._example_text` expects `body`); the
            # default keeps the legacy body-less shape for callers that only
            # persist IDs/URLs/reasons.
            record["body"] = row["body"]
        out.append(record)
    return out


def retrieve_examples_for_generation(
    packet, *, voice, mode, corpus_path, analysis_dir, top_n=3, exclude_ids=(), target_chars=None
):
    """Generation preflight (Review G3): return exactly `top_n` unique style
    examples — WITH bodies for the prompt — or raise before any model call.

    Composition fallback uses the already documented M2.3 chain, never a new
    taxonomy:

    ```text
    requested VOICE + MODE
    -> HOUSE + same MODE          (only when a non-HOUSE voice was requested)
    -> HOUSE + STANDARD_NEWS      (only when the mode itself differs)
    ```

    Article IDs are deduplicated across steps. Returns
    `{examples, fallback_used, fallback_trail, retrieval_reason}`; the trail and
    reason are truthful, so the caller persists what really happened instead of
    a hard-coded `fallback_used=False`.
    """
    steps = [(voice, mode)]
    if voice != "VOICE_HOUSE":
        steps.append(("VOICE_HOUSE", mode))
    if mode != "MODE_STANDARD_NEWS":
        steps.append(("VOICE_HOUSE", "MODE_STANDARD_NEWS"))
    picked: dict = {}
    trail = []
    excluded = set(exclude_ids or ())
    for step_voice, step_mode in steps:
        if len(picked) >= top_n:
            break
        found = retrieve_examples(
            packet,
            voice=step_voice,
            mode=step_mode,
            corpus_path=corpus_path,
            analysis_dir=analysis_dir,
            top_n=top_n,
            exclude_ids=sorted(excluded),
            target_chars=target_chars,
            include_body=True,
        )
        for example in found:
            picked.setdefault(example["article_id"], example)
        excluded = set(picked)
        trail.append({"voice": step_voice, "mode": step_mode, "found": len(found)})
    examples = list(picked.values())[:top_n]
    if len(examples) < top_n:
        raise StyleRetrievalError(
            f"стилови примери: само {len(examples)}/{top_n} уникални за "
            f"{voice}+{mode} (верига: {trail}) — отказана генерация преди моден разход"
        )
    fallback_used = len(trail) > 1
    if fallback_used:
        fallback_steps = " -> ".join(f"{v}+{m}" for v, m in steps[1 : len(trail)])
        retrieval_reason = f"fallback: {voice}+{mode} -> {fallback_steps}"
    else:
        retrieval_reason = f"{voice}+{mode} (requested composition, no fallback needed)"
    return {
        "examples": examples,
        "fallback_used": fallback_used,
        "fallback_trail": trail,
        "retrieval_reason": retrieval_reason,
    }
