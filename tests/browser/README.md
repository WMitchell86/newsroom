# D2A browser parity harness

Real Chromium against the **Python-served production bundle**. This is the
browser-level proof that D1 could not give: hydration, React Router navigation,
refresh, deep links and back/forward over the compiled Vite build.

The production topology under test is exactly:

```text
real browser -> existing Python ThreadingHTTPServer -> compiled Vite SPA
             -> same-origin /api/v1 -> canonical stores
```

There is **no** Vite dev server, **no** Vite preview, **no** mocked API client and
**no** intercepted fake response in the parity proof.

## Install

The only added dependency is Playwright (test-only; it is not a runtime
dependency of the product and is not imported by any product module).

```bash
python3 -m pip install playwright==1.63.0
python3 -m playwright install chromium
```

Only Chromium is installed — that is the single engine this gate needs.

> If the environment is PEP 668 managed and rejects a system install, install
> into a target directory and put it on `PYTHONPATH`:
>
> ```bash
> python3 -m pip install --target=/tmp/d2a-pydeps playwright==1.63.0
> export PYTHONPATH=/tmp/d2a-pydeps:$PWD/src
> ```

## Run

```bash
cd frontend && npm ci && npm run build && cd ..
PYTHONPATH=src python3 -m pytest tests/browser -p no:cacheprovider
```

The suite skips itself (rather than failing) when the production build or the
browser is missing, so it is safe to invoke anywhere.

## What is real and what is substituted

Real, end to end: React, the Vite production build, the Python
`ThreadingHTTPServer`, `/api/v1`, the operation registry and its worker threads,
the readiness/orchestration layer, every canonical store, the C4 validation
engine, the C5 finalization digest re-check, and the story/collector pipelines.

Substituted — and **only** these three outbound edges, where production code
leaves the process:

| Edge | Substitute | Kept real |
| --- | --- | --- |
| Model transport | `generate._call_gemini` / `_call_openrouter` | role policy, router, usage/health records, draft orchestration, evidence audit |
| Search + page fetch | `search.provider_chain`, `web_fetch.fetch_page` | query planning, constraint evaluation, source bundle, research store, projection |
| Newsroom collector bytes | `sources.fetcher.fetch_bytes` | RSS parsing, dedup, inbox ingestion, identity grouping, source health |

Isolation is **environment/store configuration only** (`WB_NEWSROOM_DIR`,
`WB_EDITORIAL_WORKFLOW_DIR`, `MODEL_USAGE_DIR`, `MODEL_HEALTH_PATH`,
`WB_SPA_DIST`, `WB_EDITOR_FRONTEND`). There is no product test mode: no
`if E2E_TEST` branch, no test control in the SPA, and no change to any file
under `frontend/src` or `src/editor_assistant`.

## Data safety

Every browser test runs against an isolated newsroom/editorial/runtime root. The
repository's real `var/editorial_workflow` and `var/newsroom` stores are hashed
with SHA-256 **before the first test and after the last one**, by a
session-scoped autouse fixture. Any changed byte fails the run. This is an
explicit automated assertion, not an assumption.

## Screenshots

`test_capture_owner_review_screenshots` writes eight 1440x1080 PNGs of the
Python-served SPA to `var/d2a_screenshots/` (git-ignored, like all `var/`
artifacts):

```text
01-dnes.png              05-article-draft.png
02-stories-list.png      06-article-ready.png
03-story-workspace.png   07-archive-detail.png
04-article-preparation.png  08-settings.png
```

Run just that test to refresh them:

```bash
PYTHONPATH=src python3 -m pytest tests/browser/test_d2a_topology.py \
  -k screenshots -s -p no:cacheprovider
```

## CI

This is an **explicit integration gate**, deliberately not part of the normal
unit suite: it needs a compiled frontend build and a ~120 MB Chromium download.
Documented command above; the normal `pytest tests` run excludes `tests/browser`
by keeping it a separate directory that CI does not invoke. Do not weaken the
local proof to fit CI.

## Layout

| File | Covers |
| --- | --- |
| `conftest.py` | isolated runtime, real servers, browser, console/network error gate, store-integrity manifest |
| `fixture_data.py` | deterministic Story/Article fixture + the three boundary substitutes |
| `helpers.py` | role/label locators and shared assertions |
| `test_d2a_navigation.py` | boot, primary nav, deep links, refresh, back/forward, unknown routes |
| `test_d2a_stories.py` | Stories list, Story Workspace, Story actions |
| `test_d2a_operations.py` | `Проучи още`, `Обнови` |
| `test_d2a_articles.py` | full Article lifecycle, autosave, conflict, Ready, Finalize |
| `test_d2a_topology.py` | assets/fonts, screenshots, route ownership, legacy smoke, a11y, performance |
