# Coding Harness — V1.2-G4.3 Browser Acceptance

## Starting point

Current clean repository state. Expected gates:

```text
44 tests in tests/test_natural_draft_loop.py
275 passed across the files this slice touches
ruff = 1 pre-existing finding
real product proof = 3/3 drafts, rewrite 72->55 words, basis unchanged
```

This is an **acceptance pass, not an implementation task**. The feature is
built and proven. Do not change functionality unless a tested scenario fails.

**Run against the actual production server and the owner's real runtime config
and model policy.** No isolated substitute policy, no stubbed model, no
temporary store — the whole point is to confirm the thing the owner will use.

---

# Scope

Verify five end-to-end scenarios in the browser:

1. `Днес → Чернова` on a real Story → the automatic bounded enrichment runs →
   a visible, non-empty Bulgarian Draft appears.
2. A slow or failing enrichment does **not** prevent the Draft; the bounded
   timeout degrades to a warning on the Draft.
3. An existing Draft → editor comment → `Пренапиши` → the **same** Article gets
   a new content version, the previous text is still recoverable, and there are
   **zero** search/research calls.
4. Change `Стил` (voice) → `Пренапиши` → the selected Voice reaches the
   generation prompt and changes the style while the facts stay put.
5. A browser reload preserves the Draft text, the selected Voice, autosaved
   content, and the rewrite/feedback state.

For scenario 3, the "zero search/research calls" check is the sharp one: the
rewrite path must use `_draft_snapshot(article_id, enrich=False)`. Instrument or
observe the calls — do not infer it from the UI.

For scenario 2, the honest-wording check matters too: a cut-off enrichment must
say "could not be performed", not "found no additional sources".

---

# Constraints

- Do **not** start G5 or any new feature.
- Do not change behaviour unless a scenario fails. If one does, fix the defect,
  not the test.
- Do not weaken an assertion to make a scenario pass.
- The runtime stores under `var/` must not be unintentionally modified by the
  test run. Prove it: hash `var/newsroom` and `var/editorial_workflow` before and
  after, and report the result. (A rewrite during acceptance legitimately writes
  to `var/editorial_workflow`; say so explicitly rather than claiming no change.)

---

# Report — report ONLY these four things

1. **PASS/FAIL for each of the five scenarios**, with the observed evidence for
   each (what you saw, not what you expected).
2. **Any defect found, and whether it was fixed** — with file:line and the
   specific failure.
3. **Actual browser proof** — screenshots or a transcript showing the Draft, the
   rewrite before/after, and the voice change.
4. **Confirmation about the real runtime stores** — the before/after hashes and
   what changed.

If everything passes, say so plainly. If something fails, do not paper over it.

**STOP after this report.**
