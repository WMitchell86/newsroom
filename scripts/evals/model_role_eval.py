#!/usr/bin/env python3
"""M4D role qualification: which model is good enough for which role?

Generic leaderboards do not answer this — the question is whether a candidate
model handles *our* tasks (mechanical entailment, story relation, angle
assessment, Bulgarian drafting, research planning) well enough to be trusted with
that role. This harness answers it with small, meaningful fixture corpora and the
**production prompts** of each role.

```bash
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --list
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role judge
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role story --repeats 3
PYTHONPATH=src python3 scripts/evals/model_role_eval.py --role all --limit 2
```

Design rules:

* candidates come from the role's own policy routes (no hand-written model list);
* each candidate is judged on the metrics that role actually needs — for `story`
  the primary failure metric is a **false merge**, for `judge` it is a **false
  positive**;
* one prompt per case per candidate; `--repeats` (default 1, max 5) adds a tiny
  stability check on the hardest cases only;
* nothing here is production: the harness only calls the router and writes a JSON
  result under `var/model_role_eval/`. It never writes the usage ledger's prompts
  and never touches the story store or the inbox.

The promotion rule (PART 14) stays human: evaluate, drop the clearly inadequate,
keep the cheapest model that passes plus one stronger fallback.
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

from editor_assistant.drafting import model_policy, model_router
from editor_assistant.workflow import story_relation

FIXTURE_DIR = ROOT / "fixtures" / "evals" / "model_roles"
DEFAULT_OUT = ROOT / "var" / "model_role_eval"
MAX_REPEATS = 5


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


JUDGE_PROMPT = """Ти си строг съдия. Отговори САМО с JSON.
ФАКТ: {fact}
ОТРЯЗЪЦИ (единствен източник):
{support}
Върни СТРОГО: {{"entailed": true|false, "reason": "..."}}
true САМО ако всяко твърдение (деятел, отношение, статус, числа,
отрицания) е изрично подкрепено. Без външни знания.
"""

DRAFT_PROMPT = """Напиши кратък новинарски текст (2-4 изречения) по подадените ФАКТИ.
Използвай САМО числата и имената от фактите. Не добавяй нови числа.
Върни СТРОГО JSON: {{"headline": "...", "body": "..."}}

ФАКТИ:
{facts}
"""

RESEARCH_PROMPT = """Ти планираш проучване за редакция. По темата посочи какво липсва.
Върни СТРОГО JSON: {{"questions": ["...", "..."]}} (максимум 5 въпроса, без да повтаряш темата)
ТЕМА: {topic}
ИЗВЕСТНИ ФАКТИ:
{facts}
"""


def _parse_json(raw):
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def prompt_for(role, case):
    """The production prompt contract for the role (reused where possible)."""
    if role == "judge":
        return JUDGE_PROMPT.format(fact=case["fact"], support="\n---\n".join(case["support"]))
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
        context = {
            "candidate_title": case["candidate_title"],
            "candidate_publisher": case.get("candidate_publisher", ""),
            "candidate_published_at": case.get("candidate_published_at", ""),
            "candidate_summary": case.get("candidate_summary", ""),
            "representative_title": case["story_title"],
            "origin_title": case.get("story_origin_title", ""),
            "development_titles": case.get("story_developments") or [],
            "publications": publications,
        }
        return story_relation.render_prompt(context)
    if role == "angle":
        return (
            "Оцени дали предложеният ъгъл е публикуваем по подадените факти.\n"
            "Върни СТРОГО JSON: "
            '{"semantic_status": "PUBLISHABLE_ANGLE|POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH|'
            'NO_PUBLISHABLE_ANGLE", "semantic_reason": "...", "research_questions": []}\n'
            f"ПРЕДЛОЖЕНИЕ: {case['proposal']}\n"
            "ФАКТИ:\n" + "\n".join(f"- {f}" for f in case["facts"])
        )
    if role == "draft":
        return DRAFT_PROMPT.format(facts="\n".join(f"- {f}" for f in case["facts"]))
    if role == "research":
        return RESEARCH_PROMPT.format(topic=case["topic"], facts="\n".join(case["facts"]))
    raise SystemExit(f"unknown role: {role}")


# ---------------------------------------------------------------- scoring


def score(role, case, answer, raw, latency_ms, ok):
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
    }
    if not ok:
        out["detail"] = "no model answer"
        return out

    if role == "judge":
        parsed = _parse_json(raw)
        out["valid"] = isinstance(parsed, dict) and isinstance(parsed.get("entailed"), bool)
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
        parsed = _parse_json(raw)
        status = (parsed or {}).get("semantic_status")
        out["valid"] = status in (
            "PUBLISHABLE_ANGLE",
            "POTENTIALLY_PUBLISHABLE_NEEDS_RESEARCH",
            "NO_PUBLISHABLE_ANGLE",
        )
        if out["valid"]:
            out["predicted"] = status
            out["correct"] = status == case["status"]
            # Catastrophic error: calling a routine, non-newsworthy item publishable.
            out["false_positive"] = status == "PUBLISHABLE_ANGLE" and case["status"] == (
                "NO_PUBLISHABLE_ANGLE"
            )
        return out

    if role == "draft":
        parsed = _parse_json(raw)
        headline = str((parsed or {}).get("headline") or "").strip()
        body = str((parsed or {}).get("body") or "").strip()
        out["valid"] = bool(headline and body)
        if not out["valid"]:
            return out
        text = f"{headline}\n{body}"
        allowed_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", " ".join(case["facts"])))
        used_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", text))
        invented = sorted(used_numbers - allowed_numbers)
        # Required facts: a distinctive token of each fact must appear.
        missing = [
            token for token in case.get("must_mention") or [] if token.lower() not in text.lower()
        ]
        out["correct"] = not invented and not missing
        out["detail"] = (
            f"invented numbers: {invented or '—'}; missing: {missing or '—'}; "
            f"words: {len(text.split())}"
        )
        out["invented_numbers"] = invented
        out["missing_mentions"] = missing
        return out

    if role == "research":
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
        "median_latency_ms": int(statistics.median(latencies)) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "repeats": repeats,
        "verdict": "",
    }
    if not calls:
        summary["verdict"] = "NO_ANSWER"
    elif role == "story" and summary["false_merges"]:
        summary["verdict"] = "REJECT (false merge)"
    elif role == "story" and summary["false_developments"]:
        summary["verdict"] = "REJECT (false development)"
    elif role == "judge" and summary["false_positives"]:
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


def _single_route_policy(base, role, route):
    policy = json.loads(json.dumps(base))
    policy["roles"][role]["routes"] = [dict(route)]
    return model_policy.normalize(policy)


def candidates_for(policy, role, limit=None):
    rows = policy["roles"][role]["routes"]
    if limit:
        rows = rows[:limit]
    return rows


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
):
    call_role = call_role or model_router.call_role
    cases = load_cases(role)
    results = []
    if not cases:
        report = {
            "role": role,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "policy_hash": model_policy.policy_hash(policy),
            "note": f"няма фикстура за ролята ({FIXTURE_DIR / (role + '.json')})",
            "candidates": [],
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{role}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report
    for route in candidates_for(policy, role, limit=limit):
        route_policy = _single_route_policy(policy, role, route)
        rows = []
        for repeat in range(max(1, min(repeats, MAX_REPEATS))):
            for case in cases:
                started = time.monotonic()
                raw, ok = "", True
                try:
                    raw, _meta = call_role(
                        role, prompt_for(role, case), policy=route_policy, timeout=timeout
                    )
                except model_router.RoleUnavailable:
                    ok = False
                latency_ms = int((time.monotonic() - started) * 1000)
                row = score(role, case, None, raw, latency_ms, ok)
                row.update(
                    {
                        "case": case.get("id") or case.get("candidate_title"),
                        "repeat": repeat,
                        "model": route["model"],
                        "provider": route["provider"],
                        "raw": (raw or "")[:600] if show_raw else "",
                    }
                )
                rows.append(row)
                if show_raw:
                    print(f"    raw[{route['model']}][{row['case']}]: {row['raw'][:200]!r}")
        results.append(
            {
                "model": route["model"],
                "provider": route["provider"],
                "billing": route.get("billing"),
                "summary": summarize(role, rows, repeats),
                "rows": rows,
            }
        )
    report = {
        "role": role,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy_hash": model_policy.policy_hash(policy),
        "candidates": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{role}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def render(report) -> str:
    if not report.get("candidates"):
        return f"== {report['role']} == няма фикстура/кандидати — нищо не е оценено"
    lines = [f"== {report['role']} =="]
    for candidate in report["candidates"]:
        s = candidate["summary"]
        lines.append(
            f"  {candidate['provider']}:{candidate['model']} [{candidate.get('billing')}] -> "
            f"{s['verdict']} · правилни {s['correct']}/{s['cases']} · валидни {s['valid']} · "
            f"фалшиви сливания {s['false_merges']} · "
            f"фалшиви развития {s['false_developments']} · "
            f"фалшиви положителни {s['false_positives']} · "
            f"медиана {s['median_latency_ms']} ms"
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
    args = parser.parse_args(argv)

    policy = model_policy.load_policy()
    roles = list(model_policy.ROLES) if args.role == "all" else [args.role]

    if args.list:
        for role in roles:
            cases = load_cases(role)
            print(
                f"{role}: {len(cases)} случая"
                if cases
                else f"{role}: 0 случая (няма фикстура още — ролята е дефинирана, но не е квалифицирана)"
            )
            for route in candidates_for(policy, role, limit=args.limit):
                print(
                    f"  - {route['provider']}:{route['model']} [{route.get('billing')}]"
                    f"{' (paid disabled)' if route.get('billing') == 'paid' and not policy['global']['paid_enabled'] else ''}"
                )
        return 0

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
