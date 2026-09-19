# M3A Stabilization Report — 2026-09-19

Part A of `m3/HARNESS_PROMPT_M3A_STABILIZE_M3J_JEV.md`. Reliability/hygiene
only: no editorial logic, no rubric, no routing, no M3A redesign.

```text
M3A_STABILIZATION = PROVEN
```

Base commit `60d09d2`; final suite **512 passed** offline (was 481).

## A1 — Baseline reproduced

`PYTHONPATH=src pytest -q` collects **481** at the start of the pass. This
workstation has DNS, so the 8 DNS-dependent failures in
`tests/test_search_foundation.py` / `tests/test_tinyfish_adapters.py` described
by the audit were not reproduced here — but they were real *test-hygiene* debt
(see A2) and are now impossible by construction.

## A2 — Hermetic search/fetch tests

`tests/conftest.py` installs an **explicit autouse test resolver**: public
fixture hostnames map to a known public IP (`93.184.216.34`), IP literals
resolve to themselves (so private/loopback rejection stays real), and anything
else fails closed with `socket.gaierror` — exactly how the production guard
treats unresolvable hosts. The production SSRF guard (`web_fetch.guard_target`)
is **not** disabled or weakened; it runs unchanged against the deterministic
resolver.

The two tests that previously reached a *real* opener
(`run_search_operation` → `web_fetch.fetch_page`) now inject an offline
`page_opener`, closing the remaining real-HTTP dependency.

New proofs:
- `test_hermetic_resolver_maps_public_fixture_hosts_offline`
- `test_unresolvable_host_fails_closed`
- `test_private_and_local_targets_rejected` (unchanged, still verifies rejection)

Verified by re-running the whole suite with global DNS forced to fail:

```text
481 passed  (all patches in place; no real DNS, no real external HTTP)
```

## A3 — One canonical live-evidence store

`src/editor_assistant/workflow/live_store.py` is now the single writer for
`live_evidence.jsonl`:

```text
read_live_evidence(path=None)
save_live_evidence_row(row, path=None)
```

- identical JSON schema (one object per line keyed by `evidence_id`);
- deterministic ordering (`evidence_id`) and bytes (`sort_keys=True`,
  `ensure_ascii=False`);
- atomic same-directory temp file + `os.replace` (+ `fsync`);
- **serialization happens before the file is touched**, so a bad row can never
  truncate the store;
- caller-selectable path; no editorial logic; no generic repository abstraction.

`workflow/cli.py::_live_rows/_save_live_row` and
`workflow/workbench/state.py::_live_evidence_rows/_live_evidence_save` are now
thin delegations to it (public names kept). `tests/test_live_store.py` proves
upsert, deterministic bytes/order, non-truncation on failure, and that CLI and
Workbench share one implementation.

## A4 — `CURRENT_STATE.md`

Root-level `CURRENT_STATE.md` added as the first document for future harness
runs: checkpoint, verdicts, frozen boundaries, active Search routing, test
count, commands, editor-feedback state, allowed next work, optional env vars,
authoritative reports — and the explicit statement that `handoff.md` /
`MILESTONE.md` are history and old `HARNESS_PROMPT_*.md` are not current
instructions. `agents.md` read order updated to
`CURRENT_STATE.md → agents.md → current milestone/report → history`.

## A5 — Tracked M3A smoke

`tmp/m3a_smoke.py` (scratch/untracked) promoted to **`scripts/m3a_smoke.py`**;
README/RUNBOOK/workbench-report references updated. It still runs against a
**copy** of the store, never the pending editor pilot, and verifies the real
store hash stays unchanged. Verified: **25/25**, real store byte-identical.

No other `tmp/` experiment was promoted.

## A6 — No style refactor

`workbench/state.py`, `workbench/html.py` and the stdlib HTTP server were left
alone. The only touch to `state.py` is the A3 delegation.

## Gate

- [x] full suite green with DNS unavailable (**512 passed**, 481 baseline + 31 new)
- [x] `ruff check src tests scripts` clean
- [x] `ruff format --check src tests scripts` clean
- [x] `scripts/m3a_smoke.py` **25/25**, live store untouched
- [x] no production security behavior changed

Note: `ruff format` (this toolchain's version) also reformatted two
pre-existing committed files (`workflow/search.py`, `tests/test_tinyfish_adapters.py`)
to satisfy the `--check` gate — whitespace/line-wrapping only, no behavior change.
