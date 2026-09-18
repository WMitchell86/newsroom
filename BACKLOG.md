# BACKLOG — deferred ideas (do NOT implement without a new scope decision)

Per harness rule §3.3: ideas discovered mid-task go here, not into the current change.

## M1.x (Radar)
- [x] M1.1 — Source Contract + Fixture Only (fixture → parser → normalized object → local output; no network) — done
- [x] M1.2 — One Real Source, Read-Only (1 public source → fetch → parser → console/JSON; no Telegram/DB) — done (+ M1.2.1 description normalization)
- [x] M1.3 — Local State + Dedupe (SQLite; NEW / UNCHANGED / UPDATED) — done
- [x] M1.4 — Telegram TEST channel (M1.4A outbox+renderer, M1.4B manual dry-run-gated delivery) — done, live-verified
- [x] M1.5 — Alert UX calibration (steps 1–5: audit → deterministic cleanup → provenance/pagination proof → de-dup 11/19→0 → live TEST send `message_id=5`) — DONE, renderer frozen
- [ ] M1.6 — Manual poll cycle (manual command: fetch → parse/normalize → NEW/UPDATED/UNCHANGED → atomic outbox → report; NO automatic Telegram sending; ingestion and delivery separated)
- [ ] M1.7 — Scheduled polling (only after the alert format is confirmed worth automating)

## Deferred to later levels
- [ ] L2 editorial triage (risk/priority/region/type rules)
- [ ] L3 action suggestions; L4 safe drafts (allow-listed types only); L5 WordPress draft helper
- [ ] L6 follow-up/deadline memory; L7 author style (retrieved examples first, no LoRA)
- [ ] L8 routine ops (health-check, broken-link detection, parser canary)
- [ ] Ideas for later: source diff assistant, promise/deadline memory, archive capsule, storm mode

## Explicitly NOT for V1 (spec §12)
LoRA/fine-tuning, generic NER platform, large gazetteer, CRM, pgvector-by-default,
enterprise social listening, autonomous hard-news writing, closed-FB-group scraping,
complicated confidence scoring, 80-source Playwright farm, heavy multi-agent newsroom.

## M2+ deferred by editor decisions (do NOT implement without a new scope decision)
- [ ] Provider-health/cooldown for repeated same-day DDGS degradation (observed
      M2S-R3/R3b; for now observable via the failure taxonomy, not a redesign trigger)
- [ ] TinyFish fetch fallback promotion — only if real cases show it saving pages
      (current verdict: TINYFISH_FETCH = AVAILABLE / NOT_YET_PROVEN, narrow
      failure-category trigger only)
- [ ] Semantic correction CONCRETE_ACTION_NEEDS_RESEARCH vs ROUTINE_REPORT_VETO —
      FROZEN until the editor V2 sample review (hypotheses + evidence:
      m2/review/SHADOW_DISAGREEMENT_ENRICHMENT_AUDIT.md)
- [ ] Monid integration — backlog (explicitly not in the runtime path)
- [ ] LIVE 6–10 — not yet (gated on the editor V2 sample review)
