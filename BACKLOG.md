# BACKLOG — deferred ideas (do NOT implement without a new scope decision)

Per harness rule §3.3: ideas discovered mid-task go here, not into the current change.

## M1.x (Radar)
- [x] M1.1 — Source Contract + Fixture Only (fixture → parser → normalized object → local output; no network) — done
- [x] M1.2 — One Real Source, Read-Only (1 public source → fetch → parser → console/JSON; no Telegram/DB) — done (+ M1.2.1 description normalization)
- [x] M1.3 — Local State + Dedupe (SQLite; NEW / UNCHANGED / UPDATED) — done
- [x] M1.4 — Telegram TEST channel (M1.4A outbox+renderer, M1.4B manual dry-run-gated delivery) — done offline; live send pending

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
