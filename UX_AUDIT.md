# UX_AUDIT — M1.5 Editorial Alert UX Calibration (step 1: audit only, no code changes)

Date: 2026-09-12 · Evidence base: 19 real PENDING alerts (live feed ingest of 2026-09-11/12),
5 rendered previews (one per document type) in `var/ux_previews_2026-09-12.txt` (local, not sent).
Nothing below is implemented — this is a decision sheet for the editor-in-chief.

## Measured evidence (19/19 items)

| Signal | Finding |
|---|---|
| Message length | 560–1996 chars (Telegram plain text, no parse_mode) |
| Excerpt length | 324–501 chars; **10 of 19 hit the 500-char cap** |
| Items with "Документ" link | **19/19** (48 links total; one item has **14** attachments) |
| Registry-pattern titles | **19/19** — title = "ДОКЛАДНА ЗАПИСКА 08-00 NNNNN / date", zero human titles |
| Header line | identical in all 19: `[NEW] burgas-municipal-council` (zero scan signal) |
| Boilerplate in excerpts | "ФАЙЛОВЕ И РЕСУРСИ" 16/19 · "ВКЛЮЧЕНО В ПРЕДСТОЯЩО ЗАСЕДАНИЕ…" 13/19 · webmaster credit "zh.gospodinova Пет. | dd.mm.yyyyг. | HH:MMч." 13/19 · title repeated verbatim inside excerpt in most items |

## Answers to the 8 calibration questions

1. **Is `[NEW] burgas-municipal-council` human enough?** No. It is a machine id, identical in
   every message. Recommendation: deterministic source_id → human label map
   (`Общински съвет – Бургас`). Label maps 1:1 to a declared source — no invented facts.
2. **Title first?** Title already is first — but the title is a registry number, so the
   *subject* ("относно: …") is what an editor scans for, and it sits mid-excerpt after a
   ~130-char bureaucratic prefix. Consider promoting a deterministic "subject line"
   (text after "относно:" up to the credit-line marker) — pure parsing, source-specific
   rule with fallback to the raw excerpt.
3. **Is the 500-char excerpt too much?** As rendered, yes for scanning — 10/19 hit the cap
   and the informative core is 2–3 lines buried in noise. Treat cap and noise separately:
   first strip boilerplate, then re-evaluate cap (likely 250–300 suffices).
4. **Is the date useful?** Useful for freshness triage, but `2026-09-11T13:23:57+00:00` is
   UTC-ISO (machine form). Bulgarian editors scan `11.09.2026 16:23` (EET). Recommend
   BG-format, local time (helper `format_published_bg` already exists unused).
5. **Are "Източник:" / "Документ:" clear?** Words yes; order and volume no. The actionable
   link (the PDF) currently comes *after* the source page, and multi-attachment items
   explode into 28+ link lines (id=7 is 1996 chars, mostly "Документ:\nURL" pairs).
6. **PDF directly under the title?** Viable — but selecting "the" document among 14
   attachments (PDF + DOC + 12 XLS appendices) needs a deterministic rule
   (e.g. `*sayt.pdf` / registry-number match, fallback: first PDF, else first link).
   Risk: mislabeled attachment = implied editorial judgment. Alternative: compact
   "Документи (2): PDF, DOCX" listing without claiming which is "the" document.
   **Decision needed.**
7. **Does council boilerplate make the excerpt noisy?** Massively (see table). The noise is
   structural CMS chrome, not information → deterministic strip-list is justified.
8. **Can an editor decide "worth opening" in 2–3 s?** Not today: identical header + registry
   title + buried subject. With (1) human label, (2) subject-line promotion, (7) noise
   strip — the decisive lines would sit in the first 3 lines.

## Key architectural recommendation (for the implementation milestone, not now)

Do noise-stripping/subject-extraction **at render time**, not in `html_desc` normalization.
Reason: fingerprints cover `body_text`; re-normalizing the stored text would flip all 20
items to UPDATED and enqueue a v2 wave (fingerprint churn). Render-time transforms keep
state/fingerprints stable and preserve raw source data. Any change stays deterministic
pure functions + tests; emoji (`🆕`/`📄`) render fine in Telegram plain text if the editor
prefers them over `[NEW]`/`[UPDATED]`.

## Decisions requested from the editor (answer inline)

- [ ] D1 — BG human label for the source (recommend: yes, "Общински съвет – Бургас")
- [ ] D2 — Promote "относно:" subject as first content line (recommend: yes)
- [ ] D3 — Strip-list contents (title repeat / ФАЙЛОВЕ И РЕСУРСИ / ВКЛЮЧЕНО В… /
      webmaster credit / "Приложение N" tails) — mark which are safe to drop
- [ ] D4 — Excerpt cap after de-noising (recommend: 250–300, review with real renders)
- [ ] D5 — Date format (recommend: `дд.мм.гггг чч:мм` EET)
- [ ] D6 — Document links: single "main doc" selection vs. compact multi-doc list vs. status quo
- [ ] D7 — Emoji (🆕/📄/🔗) vs. `[NEW]`/plain labels
- [ ] D8 — Link order (Документ before Източник?)

## Non-goals for this step
No code changes, no sends (19 rows remain PENDING untouched), no scheduler. Implementation
becomes the next narrowly-scoped milestone after D1–D8 answers.

---

## Addendum (2026-09-12, M1.5 steps 2–3)
- **D1–D7 were implemented in step 2** (see MILESTONE.md): display name, subject promotion,
  boilerplate strip-list, 280-char cap after cleaning, BG local time, compact attachments
  (+N още), emoji markers. D8 kept the source page last.
- **§8 duplicate finding, measured on real data: 11/19** cleaned excerpts repeat the
  display subject verbatim (recorded, NOT solved). Candidate future rule (needs approval):
  if the cleaned excerpt substantially repeats display_subject, drop the repeated leading
  text and continue from the first new informative sentence.
- Also observed: 3/19 subject lines exceed 300 chars (max 343; Telegram 4096 unaffected).
- Provenance/pagination audit (step 3): single source `burgas-municipal-council`, zero
  integrity violations (0 duplicate identities, 0 orphans, 0 duplicate version intents);
  **no pagination code exists in ingestion** — documented, none invented.
