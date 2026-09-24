#!/usr/bin/env python3
"""M4D role qualification: which model is good enough for which role?

Generic leaderboards do not answer this — the question is whether a candidate
model handles *our* tasks (mechanical entailment, story relation, angle
assessment, Bulgarian drafting) well enough to be trusted with that role. This
harness answers it with small fixture corpora and the **production contracts**
of each role — and it reports honestly where production fidelity does NOT hold
(pre-frontend gate I):

```text
story     production story_relation prompt + false-merge metric   production-faithful
judge     production _ENTAIL_JUDGE_PROMPT + production parser     production-faithful
          (fixture subtype = fact entailment; the draft semantic judge is a
           SEPARATE subtype and is pending its own fixture — never merged
           into the fact-entailment metric)
angle     production _ASSESS_PROMPT (seven criteria, three real semantic
          statuses) + production parser/validation; the fixture includes the
          seven M3D shadow-disagreement cases                      production-faithful
 draft    production build_prompt() over frozen EvidencePackets + real style
          retrieval + parse_draft_json + deterministic audit/originality;
          language/style promotion is a HUMAN review sheet           production-faithful
research  synthetic plumbing fixture only — there is no production
          `role="research"` caller in the source tree
          RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED          not wired
extract   defined role, no qualification corpus
utility   defined role, no qualification corpus                     NOT_EVALUATED
```

```bash
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --list
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role judge --limit 1
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role draft --allow-paid
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role all --limit 2
```

Design rules:

* candidates come from the role's own policy routes (no hand-written model list);
* each candidate is judged on the metrics that role actually needs — for `story`
  the primary failure metric is a **false merge**, for `judge` a **false
  positive**, for `angle` a false PUBLISHABLE on routine material;
* **paid eval guard (I7):** a paid candidate route refuses to run without the
  explicit `--allow-paid` flag — a paid model in the policy file is not an opt-in;
* one prompt per case per candidate; `--repeats` (default 1, max 5) adds a tiny
  stability check on the hardest cases only;
* the draft semantic gate runs only with the explicit `--semantic-gate` flag
  (extra model calls);
* nothing here is production: the harness only calls the router and writes a JSON
  result under `var/model_role_eval/`. It never writes the usage ledger's prompts
  and never touches the story store or the inbox.

The promotion rule (PART 14) stays human: evaluate, drop the clearly inadequate,
keep the cheapest model that passes plus one stronger fallback. For `draft` the
final Bulgarian language/style decision is made on the generated human-review
sheet — never by another model.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from editor_assistant.drafting import generate as gen
from editor_assistant.drafting import model_catalog, model_policy, model_router
from editor_assistant.drafting import prompt as prompt_mod
from editor_assistant.drafting import retrieval as retrieval_mod
from editor_assistant.drafting.evidence import EvidenceError, validate_packet
from editor_assistant.style.profiles import ProfileError
from editor_assistant.workflow import discovery, story_relation

FIXTURE_DIR = ROOT / "fixtures" / "evals" / "model_roles"
DEFAULT_OUT = ROOT / "var" / "model_role_eval"
MAX_REPEATS = 5

#: Live style assets — the same paths `workflow.live` uses. The draft eval must
#: draft with the REAL Site DNA / VOICE / MODE / style corpus, not fixtures of them.
CORPUS = ROOT / "var" / "style_corpus" / "articles.jsonl"
ANALYSIS = ROOT / "var" / "style_analysis"

#: I5: there is currently no production `role="research"` call in the source
#: tree. The fixture stays for future work, but the harness never presents its
#: synthetic benchmark as production qualification.
RESEARCH_ROLE_PRODUCTION_WIRING = "NOT_IMPLEMENTED"

#: Qualification-harness truth table (reported in every run and in the review
#: report): what is production-faithful, what is not wired, what is pending.
WIRING = {
    "judge": "PRODUCTION_FAITHFUL",
    "story": "PRODUCTION_FAITHFUL",
    "angle": "PRODUCTION_FAITHFUL",
    "draft": "PRODUCTION_FAITHFUL",
    "research": RESEARCH_ROLE_PRODUCTION_WIRING,
    "extract": "NOT_EVALUATED",
    "utility": "NOT_EVALUATED",
}

#: I2: the judge fixture measures fact entailment only. The semantic judge of an
#: unpublished draft (`generate._semantic_judge_prompt`) is a DIFFERENT contract
#: and stays pending its own fixture — its metric is never merged into this one.
JUDGE_FIXTURE_SUBTYPES = {
    "fact_entailment": "PRODUCTION_FAITHFUL",
    "draft_semantic": "PENDING_NO_FIXTURE",
}


class EvalAssetsError(RuntimeError):
    """Frozen eval assets are missing/invalid — report the case as UNAVAILABLE
    instead of calling a model with a fabricated prompt (I4)."""


class EvalPaidError(RuntimeError):
    """Paid candidate routes selected without the explicit opt-in (I7)."""


#: Eval-only candidate syntax: ``provider:model`` for Gemini, and
#: ``openrouter:model#free|paid`` when billing is paid.  A model whose canonical
#: OpenRouter id ends in ``:free`` is an explicit free declaration by itself.
EVAL_ONLY = "EVAL_ONLY"


class EvalCandidateError(RuntimeError):
    """Malformed, unvalidated, or ambiguous eval-only candidate."""


def parse_eval_candidate(spec: str) -> dict:
    """Parse and normalize one explicit eval candidate without touching policy."""
    raw = str(spec or "").strip()
    if not raw or ":" not in raw:
        raise EvalCandidateError("кандидатът трябва да е provider:model")
    provider, model_and_billing = raw.split(":", 1)
    model, marker, billing = model_and_billing.partition("#")
    provider = provider.strip().lower()
    model = model.strip()
    if provider == "gemini":
        if marker or not model:
            raise EvalCandidateError("Gemini кандидатът не приема billing marker")
        route = {"provider": provider, "model": model}
    elif provider == "openrouter":
        if not model:
            raise EvalCandidateError("OpenRouter кандидатът няма model id")
        if marker:
            billing = billing.strip().lower()
        elif model.endswith(":free"):
            billing = "free"
        else:
            raise EvalCandidateError("OpenRouter eval кандидатът изисква #free или #paid")
        route = {"provider": provider, "model": model, "billing": billing}
    else:
        raise EvalCandidateError(f"непознат provider: {provider!r}")
    try:
        normalized = model_policy.normalize(
            _policy_with_only_candidate(model_policy.load_defaults(), route)
        )["roles"]["judge"]["routes"][0]
    except model_policy.PolicyError as exc:
        raise EvalCandidateError(str(exc)) from exc
    return {**normalized, "eval_only": EVAL_ONLY}


def _policy_with_only_candidate(base: dict, route: dict) -> dict:
    policy = json.loads(json.dumps(base))
    for role in model_policy.ROLES:
        policy["roles"][role]["routes"] = [dict(route)]
    return policy


# ---------------------------------------------------------------- fixtures


def load_cases(role) -> list:
    """Fixture cases for a role; an empty list when no corpus exists yet.

    `judge`/`story`/`angle`/`draft`/`research` ship seed corpora; `extract` and
    `utility` are defined roles without a qualification corpus yet, and the
    harness reports that honestly instead of inventing cases.
    """
    path = FIXTURE_DIR / f"{role}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("cases") or []


# ---------------------------------------------------------------- prompts (production contracts)


def _parse_json(raw):
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _angle_refs(case):
    """Fixture facts in the shape the production assess prompt/parser expect
    (`{fact_id, text}`); plain strings get deterministic F1..Fn ids."""
    refs = []
    for index, fact in enumerate(case.get("facts") or [], 1):
        if isinstance(fact, dict):
            refs.append(
                {
                    "fact_id": str(fact.get("fact_id") or fact.get("id") or f"F{index}"),
                    "text": str(fact.get("text", "")),
                }
            )
        else:
            refs.append({"fact_id": f"F{index}", "text": str(fact)})
    return refs


def _angle_proposal(case):
    proposal = str(case.get("new_proposition") or case.get("proposal") or "")
    return {
        "title": str(case.get("title") or proposal),
        "new_proposition": proposal,
        "reason": str(case.get("reason") or ""),
    }


def load_draft_assets(packet, *, voice, mode):
    """Real Site DNA + VOICE/MODE profiles + real style retrieval (I4).

    Uses the live `var/` paths production uses. Raises `EvalAssetsError` when
    the local style assets are missing or the corpus cannot produce exactly
    three unique examples — the eval then reports the case unavailable instead
    of spending model calls on a fabricated prompt.
    """
    try:
        site_dna = json.loads((ANALYSIS / "site_dna.json").read_text(encoding="utf-8"))
        profiles_raw = json.loads((ANALYSIS / "style_profiles.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalAssetsError(f"липсват стилови активи в {ANALYSIS}: {exc}") from exc
    by_id = {p.get("profile_id"): p for p in profiles_raw}
    voice_profile, mode_profile = by_id.get(voice), by_id.get(mode)
    if voice_profile is None or mode_profile is None:
        raise EvalAssetsError(f"липсва профил voice={voice!r} mode={mode!r} в {ANALYSIS}")
    if not CORPUS.exists():
        raise EvalAssetsError(f"липсва стилов корпус: {CORPUS}")
    try:
        retrieval = retrieval_mod.retrieve_examples_for_generation(
            packet, voice=voice, mode=mode, corpus_path=CORPUS, analysis_dir=ANALYSIS
        )
    except (retrieval_mod.StyleRetrievalError, ProfileError, OSError) as exc:
        raise EvalAssetsError(str(exc)) from exc
    return {
        "site_dna": site_dna,
        "voice_profile": voice_profile,
        "mode_profile": mode_profile,
        "examples": retrieval["examples"],
        "retrieval_reason": retrieval["retrieval_reason"],
        "fallback_used": retrieval["fallback_used"],
    }


def draft_prompt_spec(case, *, assets=None):
    """The REAL production draft prompt (I4): `build_prompt()` over a frozen
    EvidencePacket + Site DNA + VOICE + MODE + three real style examples.

    `assets` / `case["eval_assets"]` exist for hermetic tests; the default is
    the live retrieval path. Missing assets raise `EvalAssetsError` before any
    model call.
    """
    packet = case.get("packet")
    if not isinstance(packet, dict):
        raise EvalAssetsError("draft фикстурата няма замразен EvidencePacket (case.packet)")
    try:
        validate_packet(packet)
    except EvidenceError as exc:
        raise EvalAssetsError(f"невалиден EvidencePacket: {exc}") from exc
    voice = case.get("voice") or "VOICE_HOUSE"
    mode = case.get("mode") or "MODE_STANDARD_NEWS"
    if assets is None:
        assets = case.get("eval_assets")
    if assets is None:
        assets = load_draft_assets(packet, voice=voice, mode=mode)
    spec = prompt_mod.build_prompt(
        packet,
        site_dna=assets["site_dna"],
        voice_profile=assets["voice_profile"],
        mode_profile=assets["mode_profile"],
        style_examples=assets["examples"],
        task_extra=case.get("task_extra", ""),
    )
    context = {
        "style_headlines": [str(e.get("headline") or "") for e in assets["examples"]],
        "voice": voice,
        "mode": mode,
    }
    return spec, context


def build_prompt_for(role, case):
    """`(prompt_text, scoring_context)` using the role's production contract."""
    context = {}
    if role == "judge":
        # I2: production fact-entailment prompt, rendered by production code.
        return discovery.render_entail_prompt(case["fact"], case["support"]), context
    if role == "story":
        # Normalize the fixture publications into the shape `build_context`
        # produces in production, so the harness sends the production prompt.
        publications = [
            {
                "title": p.get("title", ""),
                "publisher_domain": p.get("publisher_domain", ""),
                "published_at": p.get("published_at", ""),
                "discovered_at": p.get("discovered_at") or p.get("published_at", ""),
                "summary": p.get("summary", ""),
                "relation": p.get("relation", ""),
            }
            for p in case.get("story_publications") or []
        ]
        ctx = {
            "candidate_title": case["candidate_title"],
            "candidate_publisher": case.get("candidate_publisher", ""),
            "candidate_published_at": case.get("candidate_published_at", ""),
            "candidate_summary": case.get("candidate_summary", ""),
            "representative_title": case["story_title"],
            "origin_title": case.get("story_origin_title", ""),
            "development_titles": case.get("story_developments") or [],
            "publications": publications,
        }
        return story_relation.render_prompt(ctx), context
    if role == "angle":
        # I3: the REAL production seven-criterion assessment contract, rendered
        # and (in score) validated by discovery.py — not a simplified prompt.
        return (
            discovery.render_assess_prompt(_angle_proposal(case), _angle_refs(case)),
            context,
        )
    if role == "draft":
        spec, context = draft_prompt_spec(case)
        return spec["text"], context
    if role == "research":
        # Synthetic plumbing fixture only: NOT a production contract (I5).
        facts = "\n".join(f"- {f}" for f in case["facts"])
        text = (
            "Ти планираш проучване за редакция. По темата посочи какво липсва.\n"
            'Върни СТРОГО JSON: {"questions": ["...", "..."]} '
            "(максимум 5 въпроса, без да повтаряш темата)\n"
            f"ТЕМА: {case['topic']}\nИЗВЕСТНИ ФАКТИ:\n{facts}"
        )
        return text, context
    raise SystemExit(f"unknown role: {role}")


def prompt_for(role, case):
    """The production prompt contract for the role (text only)."""
    return build_prompt_for(role, case)[0]


# ---------------------------------------------------------------- scoring


def score(role, case, answer, raw, latency_ms, ok, context=None):
    """Role-appropriate verdict. `ok` is False for a failed/empty model call."""
    out = {
        "ok": ok,
        "valid": False,
        "correct": False,
        "false_merge": False,
        "false_development": False,
        "false_positive": False,
        "latency_ms": latency_ms,
        "detail": "",
        "label_basis": "HUMAN_ADJUDICATED" if case.get("adjudicated") else "DETERMINISTIC_BASELINE",
        "infrastructure_class": "" if ok else "UNKNOWN_INFRA",
        "infrastructure_detail": "",
    }
    if not ok:
        out["detail"] = "no model answer"
        return out

    if role == "judge":
        # I2: production parser — an answer only counts when it is JSON with a
        # boolean `entailed`, exactly like `judge_fact_with_model` accepts.
        parsed = discovery.parse_entail_answer(raw)
        out["valid"] = parsed is not None
        if out["valid"]:
            predicted = bool(parsed["entailed"])
            expected = bool(case["entailed"])
            out["correct"] = predicted == expected
            # A false positive (asserting support that is not there) is the
            # dangerous error for this role.
            out["false_positive"] = predicted and not expected
        return out

    if role == "story":
        parsed = _parse_json(raw)
        try:
            relation = story_relation.parse_relation(parsed)
        except (story_relation.RelationError, TypeError):
            return out
        out["valid"] = True
        expected = case["relation"]
        predicted = relation["relation"]
        out["predicted"] = predicted
        out["correct"] = predicted == expected
        # Two different expensive mistakes, and both are reported separately
        # because they hurt the editor differently:
        #   FALSE MERGE       joining material that belongs to another story
        #   FALSE DEVELOPMENT announcing a change where nothing material changed
        out["false_merge"] = predicted in story_relation.SAME_STORY_GROUP and expected == (
            "DIFFERENT_STORY"
        )
        out["false_development"] = predicted == "NEW_DEVELOPMENT" and expected in (
            "SAME_STORY",
            "RELATED_BACKGROUND",
        )
        return out

    if role == "angle":
        # I3: production parser/validation — all seven rubric criteria scored
        # 0/1/2, positive scores citing real fact ids, one of the three real
        # semantic statuses. A status-only answer is NOT valid anymore.
        refs = _angle_refs(case)
        parsed = discovery.parse_assess_answer(raw, refs)
        out["valid"] = parsed is not None
        if not out["valid"]:
            out["detail"] = "production assess parser rejected the answer"
            return out
        status = parsed["semantic_status"]
        out["predicted"] = status
        out["deterministic_label"] = case.get("status")
        out["candidate_label"] = status
        out["correct"] = status == case["status"]
        out["stable"] = None
        out["routine_publishable_concern"] = (
            status == "PUBLISHABLE_ANGLE" and case["status"] == "NO_PUBLISHABLE_ANGLE"
        )
        # Catastrophic error: calling a routine, non-newsworthy item publishable.
        out["false_positive"] = out["routine_publishable_concern"]
        out["detail"] = f"scores {sum(v['score'] for v in parsed['scores'].values())}/14"
        return out

    if role == "draft":
        # I4: the production parse path + deterministic factual/originality
        # checks. Language/style promotion stays HUMAN (see the review sheet).
        packet = case.get("packet") or {}
        try:
            draft = gen.parse_draft_json(raw)
        except ValueError as exc:
            out["detail"] = f"parse_draft_json: {exc}"
            return out
        headline = str(draft.get("headline") or "").strip()
        body = str(draft.get("body") or "").strip()
        out["valid"] = bool(headline and body)
        if not out["valid"]:
            out["detail"] = "draft JSON missing headline/body"
            return out
        out["headline"] = headline
        out["body"] = body
        text = f"{headline}\n{body}"
        evidence_text = " ".join(
            [f.get("text", "") for f in packet.get("facts") or []]
            + [str(n) for n in packet.get("numbers") or []]
            + [packet.get("source_headline", ""), packet.get("source_text", "")]
        )
        allowed_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", evidence_text))
        used_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", text))
        invented = sorted(used_numbers - allowed_numbers)
        # Required facts: a distinctive token of each fact must appear.
        missing = [
            token for token in case.get("must_mention") or [] if token.lower() not in text.lower()
        ]
        # Deterministic production audit: unsupported sentences + style leak.
        lexical = gen.audit_claims(
            body,
            packet,
            style_texts=(context or {}).get("style_headlines") or (),
        )
        # Deterministic originality guard (warns, never blocks — same as prod).
        originality = gen.originality_check(body, packet.get("source_text", ""))
        out["invented_numbers"] = invented
        out["invented_names"] = _invented_names(text, packet)
        out["missing_mentions"] = missing
        out["unsupported"] = lexical["unsupported"]
        out["unsupported_count"] = len(lexical["unsupported"])
        out["leak_hits"] = lexical["leak_hits"]
        out["originality_pass"] = bool(originality.get("pass", True))
        out["originality_longest_run"] = int(originality.get("longest_run_words") or 0)
        out["word_count"] = len(text.split())
        out["correct"] = not invented and not missing
        out["detail"] = (
            f"invented: {invented or '—'}; missing: {missing or '—'}; "
            f"unsupported: {len(lexical['unsupported'])}; leak: {len(lexical['leak_hits'])}; "
            f"originality: {'pass' if out['originality_pass'] else 'REVIEW'}; "
            f"words: {len(text.split())}"
        )
        return out

    if role == "research":
        # Synthetic plumbing fixture — never presented as production
        # qualification (RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED).
        parsed = _parse_json(raw)
        questions = (parsed or {}).get("questions")
        out["valid"] = isinstance(questions, list) and all(isinstance(q, str) for q in questions)
        if out["valid"]:
            joined = " ".join(questions).lower()
            expected = [k.lower() for k in case.get("expect_keywords") or []]
            # Bulgarian inflects: accept a keyword or its 6-character stem
            # ("финансиране" ~ "финансира"), never a looser match than that.
            hits = [k for k in expected if k in joined or (len(k) >= 6 and k[:6] in joined)]
            out["coverage"] = round(len(hits) / max(len(expected), 1), 3)
            out["questions"] = len(questions)
            out["correct"] = bool(expected) and len(hits) == len(expected)
            out["detail"] = (
                f"coverage {out['coverage']} ({len(hits)}/{len(expected)}); "
                f"{len(questions)} questions (idle target <= {case.get('max_questions', 5)})"
            )
        return out

    raise SystemExit(f"unknown role: {role}")


def _invented_names(text: str, packet: dict) -> list:
    """Bounded proper-name check against frozen packet entities.

    This is a conservative eval signal, not a new production NER contract.  A
    capitalised phrase is reported only when it is absent from every frozen
    people/organization/place/source string.
    """
    known = " ".join(
        [
            *(packet.get("people") or []),
            *(packet.get("organizations") or []),
            *(packet.get("places") or []),
            str(packet.get("source_headline") or ""),
            str(packet.get("source_text") or ""),
        ]
    ).casefold()
    phrases = re.findall(r"\b[А-Я][а-яА-Я-]+(?:\s+[А-Я][а-яА-Я-]+){1,3}\b", text)
    return sorted({p for p in phrases if p.casefold() not in known})


def summarize(role, rows, repeats):
    calls = [r for r in rows if r.get("ok")]
    valid = [r for r in calls if r.get("valid")]
    latencies = [r["latency_ms"] for r in calls]
    summary = {
        "role": role,
        "cases": len(rows),
        "answers": len(calls),
        "valid": len(valid),
        "correct": sum(1 for r in rows if r.get("correct")),
        "false_merges": sum(1 for r in rows if r.get("false_merge")),
        "false_developments": sum(1 for r in rows if r.get("false_development")),
        "false_positives": sum(1 for r in rows if r.get("false_positive")),
        "invented_names": sum(len(r.get("invented_names") or []) for r in rows),
        "word_count": sum(int(r.get("word_count") or 0) for r in rows),
        # Draft-only deterministic counters (I4): recorded for the human review
        # decision; they warn, they do not replace it.
        "unsupported_total": sum(int(r.get("unsupported_count") or 0) for r in rows),
        "originality_warnings": sum(1 for r in rows if r.get("originality_pass") is False),
        "semantic_gated": sum(1 for r in rows if r.get("semantic_gate")),
        "semantic_reviews": sum(1 for r in rows if r.get("semantic_gate") == "FACTUAL_GATE_REVIEW"),
        "median_latency_ms": int(statistics.median(latencies)) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "repeats": repeats,
        "verdict": "",
    }
    if role == "angle":
        by_case = {}
        for row in calls:
            by_case.setdefault(row.get("case"), []).append(row)
        for case_rows in by_case.values():
            labels = {row.get("candidate_label") for row in case_rows if row.get("valid")}
            stable = (
                len(case_rows) > 1 and len(labels) == 1 and all(r.get("valid") for r in case_rows)
            )
            for row in case_rows:
                row["stable"] = stable
        seed = [r for r in rows if not r.get("m3d_disagreement")]
        disagreements = [r for r in rows if r.get("m3d_disagreement")]
        summary["seed"] = {
            "cases": len(seed),
            "valid": sum(1 for r in seed if r.get("valid")),
            "correct": sum(1 for r in seed if r.get("correct")),
            "false_positive": sum(1 for r in seed if r.get("false_positive")),
        }
        summary["m3d_disagreement"] = {
            "cases": len(disagreements),
            "valid": sum(1 for r in disagreements if r.get("valid")),
            "stable": sum(1 for r in disagreements if r.get("stable")),
            "routine_publishable_concern": sum(
                1 for r in disagreements if r.get("routine_publishable_concern")
            ),
            "label_basis": "DETERMINISTIC_BASELINE_NOT_HUMAN_ADJUDICATION",
        }

    if not calls:
        summary["verdict"] = "NO_ANSWER"
    elif role == "story" and summary["false_merges"]:
        summary["verdict"] = "REJECT (false merge)"
    elif role == "story" and summary["false_developments"]:
        summary["verdict"] = "REJECT (false development)"
    elif role == "judge" and summary["false_positives"]:
        summary["verdict"] = "REJECT (false positive)"
    elif role == "angle" and summary["false_positives"]:
        # I3: calling routine, non-newsworthy material publishable is the
        # catastrophic angle error — same rejection as a judge false positive.
        summary["verdict"] = "REJECT (false positive)"
    elif summary["correct"] == len(rows) and len(valid) == len(rows):
        summary["verdict"] = "PASS"
    elif summary["correct"] >= max(len(rows) - 1, 1):
        summary["verdict"] = "PASS_WITH_NOTES"
    else:
        summary["verdict"] = "WEAK"
    if repeats > 1:
        summary["stability_note"] = (
            "repeats apply to the fixture as a whole; a flip between runs is a "
            "stability warning, not a correctness claim"
        )
    return summary


# ---------------------------------------------------------------- runner


def _single_route_policy(base, role, route, *, allow_paid=False):
    policy = json.loads(json.dumps(base))
    policy["roles"][role]["routes"] = [dict(route)]
    if route.get("eval_only"):
        # Evaluation must not be blocked by today's production role ledger. Keep
        # the shared provider/model ledger intact, but give this derived policy
        # a bounded role budget for the fixture run.
        policy["roles"][role]["soft_calls_day"] = 1000
        policy["roles"][role]["hard_calls_day"] = 1000
    normalized = model_policy.normalize(policy)
    if allow_paid and route.get("billing") == "paid":
        normalized["global"]["paid_enabled"] = True
    if route.get("eval_only"):
        normalized["roles"][role]["routes"][0]["eval_only"] = route["eval_only"]
    return normalized


def candidates_for(policy, role, limit=None):
    rows = policy["roles"][role]["routes"]
    if limit:
        rows = rows[:limit]
    return rows


def _semantic_verdict(case, row, *, semantic_judge, timeout):
    """I4: the semantic gate runs only when explicitly requested — it is an
    extra model call, never part of the default deterministic score."""
    judge = semantic_judge or gen.verify_claims_semantic
    try:
        verdict = judge(case["packet"], row["body"], timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - unavailable judge must not fail the run
        return f"UNAVAILABLE ({type(exc).__name__})"
    return "FACTUAL_GATE_PASS" if (verdict or {}).get("pass") else "FACTUAL_GATE_REVIEW"


def write_human_review_sheet(out_dir, *, role, report):
    """I4: the human-review artifact for draft language/style promotion.

    The automatic checks (JSON validity, invented numbers, required facts,
    unsupported sentences, originality) are printed alongside; the Bulgarian
    naturalness / headline quality / site-fit / editing verdicts are blank
    ON PURPOSE — they are filled by a human, never by another model.
    """
    candidates = report.get("candidates") or []
    labels = {
        f"{c.get('provider')}:{c.get('model')}": chr(65 + i) for i, c in enumerate(candidates)
    }
    entries = []
    for candidate in candidates:
        label = labels[f"{candidate.get('provider')}:{candidate.get('model')}"]
        for row in candidate.get("rows") or []:
            if row.get("valid") and row.get("headline") and row.get("body"):
                entries.append((candidate, row, label))
    if not entries:
        return None
    lines = [
        f"# Draft role — human review sheet ({role})",
        "",
        f"Generated: {report['generated_at']} · policy {report['policy_hash']}",
        "",
        "Автоматично са записани само детерминираните проверки. Промоцията на",
        "българския естественост/заглавие/стил е ЧОВЕШКА — попълнете полетата",
        "ръчно; не се дава на друг модел.",
    ]
    for candidate, row, label in entries:
        lines += [
            "",
            "---",
            "",
            f"## CASE: {row['case']} · Candidate {label} (repeat {row.get('repeat', 0)})",
            "",
            f"headline: {row['headline']}",
            "",
            "body:",
            row["body"],
            "",
            "auto:",
            "  invented facts: " + (", ".join(row.get("invented_names") or []) or "—"),
            "  invented numbers: " + (", ".join(row.get("invented_numbers") or []) or "—"),
            "  missing: " + (", ".join(row.get("missing_mentions") or []) or "—"),
            f"  unsupported: {row.get('unsupported_count', 0)}",
            f"  originality: {'pass' if row.get('originality_pass', True) else 'REVIEW'}",
            f"  style leak: {len(row.get('leak_hits') or [])}",
            "",
            "Bulgarian naturalness: ___",
            "headline quality: ___",
            "Chernomorie fit: ___",
            "editing needed: ___",
            "notes: ___",
        ]
    lines += ["", "---", "", "## Blinding key (reveal only after review)", ""]
    for route, label in labels.items():
        lines.append(f"Candidate {label} = `{route}`")
    path = out_dir / f"{role}_human_review.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_role(
    role,
    *,
    policy,
    limit=None,
    repeats=1,
    timeout=240,
    out_dir=DEFAULT_OUT,
    call_role=None,
    show_raw=False,
    semantic_gate=False,
    semantic_judge=None,
    allow_paid=False,
    candidates=None,
):
    call_role = call_role or model_router.call_role
    cases = load_cases(role)
    results = []
    # Every report carries the wiring truth (I5/I6): production-faithful,
    # not wired, or not evaluated — never a silent implication of qualification.
    report_head = {
        "role": role,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy_hash": model_policy.policy_hash(policy),
        "wiring": WIRING[role],
        "privacy_gate_enabled": bool(policy["global"].get("privacy_gate_enabled")),
    }
    if role == "research":
        report_head["RESEARCH_ROLE_PRODUCTION_WIRING"] = RESEARCH_ROLE_PRODUCTION_WIRING
        report_head["note"] = (
            "синтетична фикстура за трениране на тръбата; няма production "
            'role="research" обаждане — това не е production квалификация'
        )
    if role == "judge":
        report_head["fixture_subtypes"] = dict(JUDGE_FIXTURE_SUBTYPES)
    if not cases:
        report = {
            **report_head,
            "note": f"няма фикстура за ролята ({FIXTURE_DIR / (role + '.json')})",
            "candidates": [],
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{role}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report
    # I7: a live eval refuses paid candidates unless the caller passed the
    # explicit opt-in. The CLI surfaces this as `--allow-paid`; a paid model
    # merely present in the policy file is never consent to spend money.
    selected_routes = (
        candidates_for(policy, role, limit=limit) if candidates is None else candidates
    )
    if not allow_paid:
        paid = [
            f"{route['provider']}:{route['model']}"
            for route in selected_routes
            if route.get("billing") == "paid"
        ]
        if paid:
            raise EvalPaidError(
                f"{role}: платни кандидати {paid} без явен opt-in — pass allow_paid (--allow-paid)"
            )
    # Build every production prompt BEFORE any model call (I4): missing style
    # assets or an invalid frozen packet must fail the case, not spend money.
    prompts: dict = {}
    contexts: dict = {}
    prompt_errors: dict = {}
    for case in cases:
        key = str(case.get("id") or case.get("candidate_title") or "")
        try:
            prompts[key], contexts[key] = build_prompt_for(role, case)
        except EvalAssetsError as exc:
            prompt_errors[key] = str(exc)
    for route in selected_routes:
        route_policy = _single_route_policy(policy, role, route, allow_paid=allow_paid)
        rows = []
        for repeat in range(max(1, min(repeats, MAX_REPEATS))):
            for case in cases:
                key = str(case.get("id") or case.get("candidate_title") or "")
                if key in prompt_errors:
                    row = score(role, case, None, "", 0, False)
                    row["detail"] = prompt_errors[key]
                    row.update(
                        {
                            "case": case.get("id") or case.get("candidate_title"),
                            "repeat": repeat,
                            "model": route["model"],
                            "provider": route["provider"],
                            "raw": "",
                        }
                    )
                    rows.append(row)
                    continue
                started = time.monotonic()
                raw, ok = "", True
                try:
                    raw, _meta = call_role(role, prompts[key], policy=route_policy, timeout=timeout)
                except model_router.RoleUnavailable as exc:
                    ok = False
                    failures = [
                        row.get("reason", "") for row in exc.trace if row.get("event") == "FAILED"
                    ]
                    skipped = [
                        row.get("reason", "") for row in exc.trace if row.get("event") == "SKIPPED"
                    ]
                    infra_class = failures[-1].split(":", 1)[0] if failures else "NO_USABLE_ROUTE"
                    infra_detail = failures[-1] if failures else "; ".join(skipped)
                    if (
                        infra_class == model_router.QUOTA_EXHAUSTED
                        and route["provider"] == "gemini"
                    ):
                        infra_class = "DEFERRED_QUOTA"
                latency_ms = int((time.monotonic() - started) * 1000)
                row = score(role, case, None, raw, latency_ms, ok, context=contexts.get(key))
                if not ok:
                    row["infrastructure_class"] = infra_class
                    row["infrastructure_detail"] = infra_detail
                if semantic_gate and role == "draft" and row.get("valid"):
                    row["semantic_gate"] = _semantic_verdict(
                        case, row, semantic_judge=semantic_judge, timeout=timeout
                    )
                row.update(
                    {
                        "case": case.get("id") or case.get("candidate_title"),
                        "repeat": repeat,
                        "model": route["model"],
                        "provider": route["provider"],
                        "m3d_disagreement": bool(str(case.get("id") or "").startswith("m3d-")),
                        "short_note": str(case.get("audit_note") or ""),
                        "raw": (raw or "")[:600] if show_raw else "",
                    }
                )
                rows.append(row)
                if not ok and row.get("infrastructure_class") in {
                    "DEFERRED_QUOTA",
                    model_router.RATE_LIMITED,
                    model_router.INVALID_MODEL,
                    model_router.AUTH_FAILED,
                    model_router.PAYMENT_REQUIRED,
                }:
                    # A route-level health failure is authoritative. Never spend
                    # the remaining fixture cases rediscovering the same outage.
                    break
                if show_raw:
                    print(f"    raw[{route['model']}][{row['case']}]: {row['raw'][:200]!r}")
        results.append(
            {
                "model": route["model"],
                "provider": route["provider"],
                "billing": route.get("billing"),
                "public_only": bool(route.get("public_only")),
                "eval_only": route.get("eval_only", "POLICY_DERIVED"),
                "catalog_status": route.get("catalog_status", "POLICY_DERIVED"),
                "availability": next(
                    (
                        row.get("infrastructure_class")
                        for row in rows
                        if row.get("infrastructure_class")
                    ),
                    "RUNTIME_AVAILABLE" if any(row.get("ok") for row in rows) else "NOT_EVALUATED",
                ),
                "summary": summarize(role, rows, repeats),
                "rows": rows,
            }
        )
    report = {**report_head, "candidates": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    if role == "draft":
        sheet = write_human_review_sheet(out_dir, role=role, report=report)
        if sheet:
            report["human_review_sheet"] = str(sheet)
    (out_dir / f"{role}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def render(report) -> str:
    wiring = report.get("wiring", "")
    if not report.get("candidates"):
        head = f"== {report['role']} == wiring: {wiring}"
        return head + "\n  няма фикстура/кандидати — нищо не е оценено"
    lines = [f"== {report['role']} == wiring: {wiring}"]
    if report["role"] == "research":
        lines.append("  RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED")
    if report["role"] == "judge":
        lines.append(
            "  fixture subtypes: fact_entailment=PRODUCTION_FAITHFUL, "
            "draft_semantic=PENDING_NO_FIXTURE"
        )
    for candidate in report["candidates"]:
        s = candidate["summary"]
        extra = ""
        if report["role"] == "draft":
            extra = (
                f" · unsupported {s['unsupported_total']} · "
                f"originality warnings {s['originality_warnings']}"
            )
            if s["semantic_gated"]:
                extra += f" · semantic review {s['semantic_reviews']}/{s['semantic_gated']}"
        lines.append(
            f"  {candidate['provider']}:{candidate['model']} [{candidate.get('billing')}] -> "
            f"{s['verdict']} · правилни {s['correct']}/{s['cases']} · валидни {s['valid']} · "
            f"фалшиви сливания {s['false_merges']} · "
            f"фалшиви развития {s['false_developments']} · "
            f"фалшиви положителни {s['false_positives']} · "
            f"медиана {s['median_latency_ms']} ms{extra}"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="M4D role qualification harness")
    parser.add_argument(
        "--role",
        default="all",
        choices=[*model_policy.ROLES, "all"],
        help="which role to qualify",
    )
    parser.add_argument("--limit", type=int, default=None, help="max candidates per role")
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="PROVIDER:MODEL[#free|paid]",
        help=(
            "eval-only exact candidate; repeatable and restricted to --role (never writes policy). "
            "OpenRouter requires #free or #paid, except canonical ids ending in :free"
        ),
    )
    parser.add_argument(
        "--validate-candidates",
        action="store_true",
        help="explicitly request live catalog validation (eval candidates are validated automatically unless --list)",
    )
    parser.add_argument(
        "--repeats", type=int, default=1, help=f"repeats per case (1-{MAX_REPEATS})"
    )
    parser.add_argument("--timeout", type=float, default=240.0, help="per-call timeout (s)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output dir")
    parser.add_argument("--list", action="store_true", help="show plan only, no model call")
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="print the raw model answer per case (human adjudication of mislabeled fixtures)",
    )
    # I7: a paid candidate route needs an explicit opt-in flag. A paid model
    # merely sitting in the policy file is NOT consent to spend money.
    parser.add_argument(
        "--allow-paid",
        action="store_true",
        help="authorise PAID candidate routes for this eval run (I7)",
    )
    parser.add_argument(
        "--semantic-gate",
        action="store_true",
        help="draft only: run the semantic factual gate too (extra model calls)",
    )
    args = parser.parse_args(argv)

    policy = model_policy.load_policy()
    roles = list(model_policy.ROLES) if args.role == "all" else [args.role]
    try:
        eval_candidates = [parse_eval_candidate(spec) for spec in args.candidate]
    except EvalCandidateError as exc:
        parser.error(str(exc))
    if eval_candidates and args.role == "all":
        parser.error("--candidate изисква конкретна --role")
    if eval_candidates and not args.list:
        validation_policy = _policy_with_only_candidate(policy, eval_candidates[0])
        for candidate in eval_candidates[1:]:
            validation_policy["roles"][args.role]["routes"].append(candidate)
        validation_policy = model_policy.normalize(validation_policy)
        catalog_report = model_catalog.validate_policy_models(validation_policy)
        selected_keys = {(r["provider"], r["model"]) for r in eval_candidates}
        selected_rows = [
            row
            for row in catalog_report["rows"]
            if (row["provider"], row["model"]) in selected_keys and row["role"] == args.role
        ]
        status_by_key = {(row["provider"], row["model"]): row["status"] for row in selected_rows}
        for candidate in eval_candidates:
            candidate["catalog_status"] = status_by_key.get(
                (candidate["provider"], candidate["model"]), "NOT_CHECKED"
            )
        for row in selected_rows:
            print(f"CATALOG_{row['status']}: {row['provider']}:{row['model']} — {row['detail']}")
        if len(selected_rows) != len(eval_candidates) or any(
            row["status"] == model_catalog.STATUS_INVALID for row in selected_rows
        ):
            parser.error("eval candidate catalog validation failed; no inference attempted")

    if args.list:
        for role in roles:
            cases = load_cases(role)
            print(
                f"{role}: {len(cases)} случая"
                if cases
                else f"{role}: 0 случая (няма фикстура още — ролята е дефинирана, но не е квалифицирана)"
            )
            print(f"  wiring: {WIRING[role]}")
            if role == "research":
                print("  RESEARCH_ROLE_PRODUCTION_WIRING = NOT_IMPLEMENTED")
            if role == "judge":
                print(
                    "  fixture subtypes: fact_entailment=PRODUCTION_FAITHFUL, "
                    "draft_semantic=PENDING_NO_FIXTURE"
                )
            selected = eval_candidates or candidates_for(policy, role, limit=args.limit)
            for route in selected:
                print(
                    f"  - {route['provider']}:{route['model']} [{route.get('billing')}]"
                    f" [{route.get('eval_only', 'POLICY_DERIVED')}]"
                    f"{' (paid disabled)' if route.get('billing') == 'paid' and not policy['global']['paid_enabled'] else ''}"
                )
        return 0

    # I7: refuse to run a paid candidate without the explicit opt-in — mirrors
    # `angle_model_ab.py --allow-paid`. Never flips `paid_enabled` itself.
    paid_candidates = [
        f"{role}:{route['provider']}:{route['model']}"
        for role in roles
        for route in (eval_candidates or candidates_for(policy, role, limit=args.limit))
        if route.get("billing") == "paid"
    ]
    if paid_candidates and not args.allow_paid:
        parser.error(
            f"платни кандидати сред избраните маршрути: {paid_candidates} — "
            "pass --allow-paid, за да оценявате платен модел (I7)"
        )

    failures = 0
    for role in roles:
        report = run_role(
            role,
            policy=policy,
            limit=args.limit,
            repeats=args.repeats,
            timeout=args.timeout,
            out_dir=Path(args.out),
            show_raw=args.show_raw,
            semantic_gate=args.semantic_gate,
            allow_paid=args.allow_paid,
            candidates=eval_candidates or None,
        )
        if not report["candidates"]:
            print(render(report))
            continue
        print(render(report))
        if not any(c["summary"]["answers"] for c in report["candidates"]):
            print(f"  (!) {role}: нито един кандидат не отговори — проверете ключове/лимити")
            failures += 1
    print(f"\nРезултати: {args.out}")
    print(
        "Промоция (PART 14): махнете очевидно неподходящите, изберете най-евтиния, "
        "който минава, и задръжте един по-силен резервен модел."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
