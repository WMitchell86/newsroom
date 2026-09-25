# Implementation Architecture v0.1 — owner-approved implementation architecture — frozen

**Date:** 2026-09-24
**Status:** owner-approved implementation architecture — frozen
**Scope:** implementation architecture for the frozen V1 editor UX

## 1. Authority and non-goals

This document is subordinate to:

- `m4/review/EDITOR_VOCABULARY_V0_1.md`
- `m4/review/INFORMATION_ARCHITECTURE_V0_1.md`
- `m4/review/EDITOR_WORKFLOWS_V0_1.md`
- `m4/review/EDITOR_WIREFRAMES_V0_1.md`
- `m4/review/STEP_6B_RENDERED_VISUAL_VALIDATION_HANDOFF.md`
- `m4/review/EDITOR_VISUAL_SYSTEM_V0_1.md`

It defines how the frozen UX can be implemented without rewriting the mature Python backend. It is the owner-approved implementation authority: implementation may begin with Phase A within this documented scope, but may not change terminology, add editorial features, or replace existing domain/safety behavior.

## 2. Executive architecture recommendation

Adopt a strangler architecture:

```text
React/Vite/TypeScript SPA
        │ same-origin /api/v1 JSON
        ▼
Thin editor API + application services
        │ projections and commands
        ▼
Existing validated Python domain/store modules
```

The smallest clean design is:

- keep the stdlib HTTP server and Python domain modules;
- add a narrow editor API/application layer, not a backend framework or rewrite;
- return editor-facing projections instead of raw Idea/EvidencePacket/Prepared/Case records;
- introduce one durable editor Article envelope for Article identity, Story lineage, three-state projection, readiness checkpoint, content version, and archive lineage;
- add narrow Story metadata for follow/bookmark and review cursor;
- implement real inline research orchestration by composing existing readiness, search, fetch, research, and provenance modules;
- retain the existing Case, EvidencePacket, Idea, Draft lineage, immutable AI Draft, safety gates, and atomic stores behind adapters;
- serve a compiled Vite SPA from the existing local Python process in production; use Vite's development proxy to that process for `/api/v1`;
- migrate incrementally while the server-rendered Workbench remains available.

No repository constraint requires GraphQL, microservices, event sourcing, Redux, or a new backend framework. The current package is intentionally stdlib-first with no required runtime dependencies (`/home/test/media/pyproject.toml:1-25`).

## 3. Architectural principles

1. **Editor vocabulary at the boundary.** The API speaks Story, Article, Publication, Facts and Sources, missing information, warnings, and frozen actions. Internal objects remain internal.
2. **Reuse domain decisions.** State transitions, evidence gates, routing, quotas, provenance, and atomic writes stay in existing Python modules.
3. **Project, do not mirror, backend records.** One API projection may join several stores; the frontend never needs to reconstruct joins or policy.
4. **Backend owns authority.** `availableActions` is computed by the backend. Every command revalidates state and policy on the server.
5. **Derived attention.** `Днес` is calculated from canonical Story and Article state; no attention queue or attention state is persisted.
6. **Narrow additions only.** Add an Article envelope and Story metadata because frozen concepts cannot otherwise be represented. Do not add a general relationship framework.
7. **Fail closed and preserve work.** Invalid transitions, blocking gaps, safety failures, and stale writes change nothing and return a stable conflict/error contract.
8. **One implementation path per behavior.** Old HTML routes may coexist temporarily, but new API commands call the same application/domain services, not a second business-logic implementation.

## 4. Current runtime and repository constraints

- Python `>=3.10`, zero required packages: `/home/test/media/pyproject.toml:1-25`.
- Local, single-user Workbench binds `127.0.0.1`; no auth: `/home/test/media/RUNBOOK.md:7-14`.
- Current server is `ThreadingHTTPServer`: `/home/test/media/src/editor_assistant/workflow/workbench/http.py:1004-1010`.
- Current routing and form dispatch are hand-written: `workbench/http.py:65-98,153-221`.
- A JSON response helper already exists but is unused for editor APIs: `workbench/http.py:117-125`.
- Current page shell is server-rendered HTML with a left rail; the frozen visual system requires top navigation, so React is a structural replacement rather than a cosmetic wrapper: `workbench/html.py:307-367`; `EDITOR_VISUAL_SYSTEM_V0_1.md:147-165`.
- There is no existing `package.json`, Vite config, TypeScript config, or frontend directory.
- Story and editorial stores are strict, validated, and mostly atomic file stores; this is suitable for the current newsroom scale and should not be migrated to a database merely to build the SPA.

The architecture therefore keeps the Python process as the runtime authority and adds a static frontend build rather than a permanent Node production server.

## 5. Current backend → frozen UX mapping

Classification:

- **Direct reuse** — existing service/domain semantics can be called unchanged.
- **Adapter/projection** — data exists but must be reshaped.
- **Partial** — meaningful primitives exist, but the frozen behavior is incomplete.
- **Missing** — no durable or executable capability exists.

| Frozen capability | Current implementation and evidence | Classification | Required boundary/gap |
|---|---|---|---|
| `Днес` derived attention | Read-only home aggregate: `workbench/http.py:231-251`; rendering `workbench/html.py:443-528` | Partial | Derive from reviewed Stories, unreviewed developments, and Articles with concrete next actions; do not persist attention rows. |
| Story grouping | `story_store.py:397-530`; `story_identity.py:342-699` | Direct reuse + adapter | Preserve raw rows and editor-locked overrides. Project editor context; do not expose discovery mechanics. |
| Story detail | `story_identity.py:740-787,802-864` | Adapter/partial | Add summary, follow flag, reviewed-development cursor, facts/gaps, related Articles, available actions. |
| Publications | Raw items: `inbox_store.py:1-54,82-169`; grouped Publications/timeline: `story_identity.py:802-864` | Direct reuse + projection | Group by `publication_key`; preserve discovery provenance; no editor-level publication state. |
| Chronology | Timeline projection in `story_identity.py:810-851` | Direct reuse + projection | Show chronology secondary; identify meaningful developments separately from the full timeline. |
| `Ново развитие` | Relation/reopen rules: `story_store.py:66-76,382-395`; classification: `story_identity.py:322-340,342-665` | Partial | Persist review cursor/bookmark metadata and produce a delta projection. Real-material recall is unproven. |
| Reviewed/ignored | Story `NEW/SEEN/IGNORED`: `story_store.py:48-73,549-572`; service: `story_identity.py:887-909` | Adapter | `Прегледай` maps to reviewed context; Publications have no independent review actions. |
| `Следи` | No Story follow/bookmark field exists | Missing | Add narrow persistent Story bookmark and review cursor; not a status. |
| Research | Search `search.py:130-157,272-401`; bundle/provenance `research.py:102-190,433-449`; gaps `readiness.py:645-695` | Partial | Add Story-scoped orchestration that runs available search/fetch, validates research, and updates facts/gaps. |
| Facts/Sources | `drafting/evidence.py:41-183`; `research.py:433-449`; `workbench/state.py:452-539,700-718` | Adapter/partial | Project Story facts and supporting Publications; Article references the Story-owned basis. |
| `Какво липсва` | Packet unknowns; readiness `readiness.py:315-370,511-597,671-695` | Adapter/partial | Project questions, conflicts, and server-assessed blocking classification. |
| Article preparation | `ideas.py:15-122`; Story bridge `workbench/state.py:1222-1300`; preparation `:1061-1117` | Partial | Create Article immediately with `story_id`, title, and focus; hide Idea/Prepared. |
| Draft generation | `live.py:192-345`; bridge `workbench/state.py:1119-1219` | Direct reuse behind one command | One `Направи чернова`; append immutable Draft and transition to `Чернова`. |
| Editing | Working copy `workbench/state.py:127-190`; case view `:601-718` | Direct reuse + adapter | Article-keyed content with revision; immutable AI Draft; manual continuation. |
| Warnings | `drafting/generate.py:567-614,788-854`; `workbench/state.py:601-655` | Direct reuse + projection | Return ID, severity, message, affected text/range when available, evidence, `blocking`. |
| Finalization | `cases.py:143-226`; service `workbench/state.py:724-799` | Direct reuse behind Article service | Require `Готова`; preserve stale/safety checks; finalize into Archive; no publish. |
| Source configuration | `sources_registry.py:1-19,82-380`; `workbench/newsroom.py:102-236` | Direct reuse | Settings projection/commands; Story evidence references Sources only. |
| AI/models | `model_policy.py:353-527`; `model_router.py:393-540,726-745`; `model_usage.py:232-362`; `model_catalog.py:82-205` | Direct reuse | Keep in Settings; no routes/traces in editorial DTOs. |
| Ingestion | `newsroom_run.py:1-31,443-728`; `intake.py:1-18,344-440`; queue/run modules | Direct reuse | Existing mechanisms remain; `Обнови` hides stages. |
| Diagnostics | `/healthz` `workbench/http.py:810-812`; `source_health.py:187-269`; model status/catalog; intake summaries | Adapter | Settings diagnostics projection; `/healthz` remains liveness only. |


### 5.1 What exists but is not directly reusable

- Current `Днес` is a Story/material/source summary aggregate, not a next-action projection.
- Current Story status has no follow bookmark or reviewed-development cursor.
- Current `Статии` joins Ideas, EvidencePackets, prepared rows, Drafts, and Cases: `workbench/state.py:954-1027`; it is not a first-class Article list.
- Current Case Workspace is Case-shaped. A Case cannot represent `Подготовка` before AI generation or a manual Draft; `finalize()` rejects evidence-only records: `workbench/state.py:724-799`.
- Research records are strongly validated but are neither attached to a canonical Story nor executed by a Story command.
- `/cases` mixes active, special, finalized, LIVE, and dry-run records; it is not Archive.

## 6. Target backend/application layers

```text
HTTP adapter (/api/v1)
  ├─ request validation / stable error mapping
  ├─ local deployment security boundary
  └─ one application query or command
             │
Application services
  ├─ today_projection
  ├─ story_projection / story_commands
  ├─ article_projection / article_commands
  ├─ archive_projection
  └─ settings_projection
             │
Adapters
  ├─ StoryStoreAdapter
  ├─ PublicationAdapter
  ├─ EditorialResearchAdapter
  ├─ ArticleRecordStore (new, narrow)
  ├─ Case/Draft/Evidence adapter
  └─ operational settings adapters
             │
Existing validated domain + stores
```

The application layer may compose existing functions. It must not duplicate evidence sufficiency, factual gating, model routing, quotas, source validation, story classification, or atomic persistence.

## 7. Target frontend architecture

### 7.1 Stack decision

| Concern | Decision | Reason |
|---|---|---|
| Build | Vite | Small static build; no backend coupling. |
| UI | React | Component model matches the approved surfaces. |
| Language | TypeScript, strict | Stable DTOs and action contracts. |
| Routing | React Router, browser history | Direct support for the frozen skeleton. |
| Server state | TanStack Query | Multiple query/mutation/invalidation surfaces and autosave status. |
| Complex forms | React Hook Form + Zod | Settings and multi-field forms only. |
| Editor text | Local reducer/controlled state | Keep typing responsive while saves are pending. |
| Global client state | No Redux/Zustand | No demonstrated cross-page need. |
| Styling | Global tokens + CSS Modules | Smallest fit for the frozen visual system. |
| Backend framework | None | Preserve stdlib server and validated services. |
| Production runtime | Python serves compiled assets | No permanent Node service. |

TanStack Query is justified, but it is not a domain layer. Query functions map one-to-one to typed API operations; mutations invalidate/update projections returned by the API.

### 7.2 Application shell and routing

```text
AppShell
├─ ErrorBoundary
├─ TopNavigation
├─ main outlet
└─ global query/error providers

/                         TodayPage
/stories                  StoryListPage
/stories/:storyId         StoryWorkspace
/articles                 ArticleListPage
/articles/:articleId      ArticleWorkspace
/archive                  ArchivePage
/archive/:articleId       FinalizedArticleView
/settings                 SettingsLanding
/settings/sources|ai|inputs|system   future subpages
```

The router contains no settings subpage implementation until a later approved slice.

### 7.3 State ownership

- **Server state:** queries, canonical projections, mutations, cache invalidation.
- **URL state:** search text and frozen list filters where appropriate.
- **Local state:** disclosure, evidence collapse, dialogs, in-progress form fields.
- **Article editor:** working text/title, confirmed server version, save status, conflict state.
- **No client-derived policy:** backend `availableActions` is authoritative.

### 7.4 Loading and errors

- Route-level pending UI must not replace already rendered content unnecessarily.
- Use contextual loading for `Обнови`, research, and Draft generation.
- Use a route error boundary for core resource failures and inline feedback for action failures.
- Never discard local text because of a refetch, save failure, or navigation.
- Use `aria-live="polite"` for passive autosave feedback.


## 8. Route architecture and migration compatibility

### 8.1 Target frontend routes

```text
/
/stories
/stories/:storyId
/articles
/articles/:articleId
/archive
/archive/:articleId
/settings
/settings/sources
/settings/ai
/settings/inputs
/settings/system
```

Internal Idea, EvidencePacket, Prepared, Case, and provider IDs never appear in primary editor URLs. `articleId` is the canonical editor Article identity, not a Case ID.

### 8.2 Same-origin API

Use `/api/v1/*` under the same Python origin. Vite development proxies `/api` to the existing Workbench port. This avoids CORS, cookie ambiguity, and a second production process.

For production browser-history routing, Python serves compiled assets and falls back to `index.html` only for unknown approved SPA routes. The fallback must never swallow `/api/v1/*`, compiled asset paths, explicit server endpoints, or legacy/operator routes. Those paths retain their own file, API, 404, or legacy response behavior.

### 8.3 Compatibility and cutover

1. Existing HTML routes remain available during development and rollback.
2. `/case/:id`, `/inbox`, and `/cases` remain legacy/operator compatibility surfaces.
3. After parity, `/case/:id` may redirect only when a canonical Article mapping exists.
4. Legacy Cases without Article lineage are not silently assigned to Stories or Articles.
5. `/inbox` and `/cases` leave primary navigation first and are deprecated later.
6. The SPA never links to legacy internal objects as normal editor destinations.

## 9. JSON API design

### 9.1 Boundary rules

- Versioned under `/api/v1`; same-origin only; no CORS in V1.
- JSON in/out; no form-encoded editor commands.
- Stable machine error codes plus Bulgarian editor messages.
- Editor DTO IDs are opaque; internal object type names are excluded.
- Every mutation validates current state/version.
- Filters are closed enums matching frozen UI.
- No generic entity/command endpoint or arbitrary filter language.

### 9.2 Error envelope

```json
{
  "error": {
    "code": "ARTICLE_VERSION_CONFLICT",
    "message": "Черновата е променена в друга сесия. Няма загубени локални промени.",
    "retryable": false,
    "fieldErrors": []
  }
}
```

Representative codes: `VALIDATION_ERROR` (400), `NOT_FOUND` (404), `INVALID_TRANSITION`/`ARTICLE_VERSION_CONFLICT`/`BLOCKING_GAP`/`SAFETY_BLOCKED` (409), `SOURCE_UNAVAILABLE` (503), and sanitized `INTERNAL_ERROR` (500).

### 9.3 `Днес`

```text
GET  /api/v1/today
POST /api/v1/today/refresh
```

`GET` returns the derived attention projection. `POST /refresh` runs collection then Story update as one `Обнови` command, hiding collect/group stages. It may use a bounded `202` operation token if the work cannot safely fit the local HTTP budget; this is transport, not an editor state.

### 9.4 Stories

```text
GET    /api/v1/stories?query=&filter=all|followed|developments|ignored
GET    /api/v1/stories/{storyId}
POST   /api/v1/stories/{storyId}/review
PUT    /api/v1/stories/{storyId}/follow
DELETE /api/v1/stories/{storyId}/follow
POST   /api/v1/stories/{storyId}/ignore
POST   /api/v1/stories/{storyId}/research
POST   /api/v1/stories/{storyId}/publications/{publicationId}/detach
POST   /api/v1/stories/{storyId}/merge
```

The last two commands are secondary grouping-correction tools.

### 9.5 Articles

```text
GET  /api/v1/articles?query=&state=all|preparation|draft|ready
POST /api/v1/stories/{storyId}/articles
GET  /api/v1/articles/{articleId}
PUT  /api/v1/articles/{articleId}/focus
POST /api/v1/articles/{articleId}/draft
PUT  /api/v1/articles/{articleId}/content
POST /api/v1/articles/{articleId}/ready
POST /api/v1/articles/{articleId}/reopen
POST /api/v1/articles/{articleId}/finalize
```

`PUT /content` is autosave transport, not a new editor action. Finalize returns an Archive link and never publishes.

### 9.6 Long operations

When a bounded command cannot complete within the local HTTP budget, return:

```http
HTTP/1.1 202 Accepted
```

```json
{
  "operationToken": "op_..."
}
```

Poll it through the single transport-only endpoint:

```text
GET /api/v1/operations/{operationToken}
```

The response exposes only bounded execution status and the command's eventual result or stable error; it is not an editor workflow object, Article/Story state, queue, or Research center. Refresh, research, and Draft-generation commands use a stable idempotency/command identity so an accepted retry cannot duplicate the same logical work.

### 9.7 Archive and Settings boundaries

`PUT /content` is autosave transport, not a new editor action. `PUT /focus` represents the frozen `Избери фокус / Промени фокуса` decision: AI may first propose text, but only an editor command stores `focus_confirmed_at`. `MAKE_DRAFT` is absent from `availableActions` until confirmation. Finalize returns an Archive link and never publishes.

```text
GET /api/v1/archive?query=
GET /api/v1/archive/{articleId}

GET/PATCH /api/v1/settings/sources
GET/PATCH /api/v1/settings/ai
GET       /api/v1/settings/inputs
GET       /api/v1/settings/system
```

Archive returns only finalized Articles, newest first, with no V1 filters. Detailed Settings schemas remain out of scope until their subpages are implemented; model routes/attempts are allowed only in technical diagnostics.


## 10. API representation models

### 10.1 Common shapes

```ts
type AvailableAction =
  | "REVIEW" | "FOLLOW" | "UNFOLLOW" | "IGNORE" | "RESEARCH_MORE"
  | "START_ARTICLE" | "SELECT_FOCUS" | "CHANGE_FOCUS" | "MAKE_DRAFT"
  | "EDIT" | "MARK_READY" | "FINALIZE";

type NextAction = {
  action: AvailableAction;
  reasonCode: string;
  label: string;
  primary: boolean;
};

type Warning = {
  id: string;
  severity: "info" | "review" | "blocking";
  message: string;
  affectedText?: string;
  range?: { start: number; end: number };
  evidenceRefs?: Array<{ publicationId?: string; sourceId?: string; locator?: string }>;
  blocking: boolean;
};

type Focus = {
  text: string;
  confirmedAt: string | null;
};
```

Labels are included for convenience, but the frontend must not invent an action absent from the server list. The backend is policy authority.

### 10.2 Story

```ts
type StorySummary = {
  id: string;
  title: string;
  summary: string;
  reviewed: boolean;
  ignored: boolean;
  followed: boolean;
  hasNewDevelopment: boolean;
  unreviewedDevelopmentCount: number;
  latestDevelopment?: NewDevelopment;
  latestChangeAt: string;
  publicationCount?: number;
  sourceCount?: number;
  availableActions: AvailableAction[];
  nextAction?: NextAction;
};

type StoryDetail = StorySummary & {
  whatHappened: string;
  factsAndSources: FactAndSource[];
  missingInformation: MissingInformation;
  publications: Publication[];
  chronology: StoryEvent[];
  newDevelopments: NewDevelopment[];
  relatedArticles: ArticleReference[];
  correction: {
    available: boolean;
    actions: Array<"DETACH_PUBLICATION" | "MERGE_STORY">;
  };
};
```

### 10.3 Publication, facts, and gaps

```ts
type Publication = {
  id: string;
  title: string;
  source: { id: string; name: string; domain?: string };
  url: string;
  publishedAt?: string;
  discoveredAt: string;
  summary?: string;
  factsAndSourceIds: string[];
};

type FactAndSource = {
  id: string;
  text: string;
  source: { id: string; name: string; url?: string };
  locator?: string;
  scope: "current" | "background";
};

type MissingInformation = {
  items: Array<{
    id: string;
    question: string;
    kind: "missing_fact" | "conflict" | "unresolved";
    blocking: boolean;
    reason?: string;
  }>;
  assessedAt: string;
};
```

### 10.4 Article

```ts
type ArticleState = "preparation" | "draft" | "ready";

type ArticleSummary = {
  id: string;
  title: string;
  story: ArticleReference;
  state: ArticleState;
  nextActionReason?: string;
  updatedAt: string;
  availableActions: AvailableAction[];
  nextAction?: NextAction;
};

type ArticleDetail = ArticleSummary & {
  editorialFocus: Focus;
  content?: { title: string; body: string; version: number };
  generatedAt?: string;
  autosave?: { status: "idle" | "saving" | "saved" | "error"; updatedAt?: string };
  warnings: Warning[];
  factsAndSources: FactAndSource[];
  missingInformation: MissingInformation;
  failure?: PointOfWorkFailure;
};
```

Finalized Articles use a read-only model with `finalizedAt`, final title/body, Story, focus, and traceability. They have no active edit actions.


## 11. Available-actions policy

`availableActions` is server-derived and included on Story and Article projections. The frontend renders it but cannot authorize a command.

The backend remains authoritative for unconfirmed focus, blocking gaps, Article state before ready/finalize, safety warnings, stale versions, allowed Story corrections, and `Готова → Чернова` when editing reopens the Article.

A proposed AI focus is displayable but does not satisfy the Draft prerequisite. `Избери фокус / Промени фокуса` atomically stores the selected text and `focus_confirmed_at`; a later confirmed change replaces both focus and confirmation timestamp. This adds no state or editor action.

Every command re-evaluates policy and returns `INVALID_TRANSITION`, `BLOCKING_GAP`, `SAFETY_BLOCKED`, or `ARTICLE_VERSION_CONFLICT` for stale client action.

## 12. Article-state mapping

Do not persist a second mutable editor `state` enum. Derive the editor state from canonical content, readiness, and finalization fields:

```text
if finalized_at != null:
    Archive
elif current body is empty:
    Подготовка
elif ready_version == content_version:
    Готова
else:
    Чернова
```

| Editor state | Canonical condition | Notes |
|---|---|---|
| `Подготовка` | No non-empty current body | Focus may be proposed or confirmed; gaps may block Draft. |
| `Чернова` | Non-empty body and no valid current readiness checkpoint | Covers AI/manual content and reopened ready Articles. |
| `Готова` | `ready_version == content_version` and the recorded validation digest is current | No automatic transition; any content or validation change invalidates readiness. |
| Archive | `finalized_at != null` and final content exists | Not active; excluded from `Статии`. |

```text
Idea → EvidencePacket → Prepared → Case/Draft   (internal)
                  ↓ projection
Подготовка → Чернова → Готова → Финализирана статия
```

`Редактирай` from `Готова` clears `ready_version`, `ready_at`, and the validation digest, so the unchanged body projects as `Чернова` until the next explicit readiness checkpoint. There is no persisted state drift and no fourth state.

## 13. Story–Article lineage design

### 13.1 Smallest durable mechanism

Add one validated, file-backed editor Article record store, for example `var/editorial_workflow/editor_articles.jsonl`, with one row per canonical Article:

```json
{
  "article_id": "art_...",
  "story_id": "s...",
  "working_title": "...",
  "editorial_focus": "...",
  "focus_confirmed_at": null,
  "created_at": "...",
  "updated_at": "...",
  "content_version": 7,
  "content_path": "var/editorial_workflow/editor_articles/{article_id}.json",
  "internal_refs": {
    "idea_id": "...",
    "evidence_id": "...",
    "case_id": "...",
    "draft_id": "..."
  },
  "ready_version": null,
  "ready_validation_digest": null,
  "ready_at": null,
  "finalized_at": null
}
```

The record intentionally has no mutable `state`. `editorial_focus` may contain an AI proposal while `focus_confirmed_at` is null. Draft generation requires a non-null confirmation timestamp. Readiness is valid only when `ready_version == content_version` and the freshly computed validation digest equals `ready_validation_digest`. `internal_refs` is never returned by the editor API.

### 13.2 Required semantics

- `story_id` is required and immutable in V1.
- `editorial_focus` plus `focus_confirmed_at` distinguishes proposal from editor confirmation.
- `article_id` is independent of Case/Evidence IDs.
- One Story may have zero, one, or many Article records.
- Story detail derives `relatedArticles` from the Article store.
- Article detail always returns its Story reference.
- Archive retains Story, confirmed focus, and evidence traceability.
- Editor state is derived; no mutable `state` is stored.
- Moving Articles between Stories is not part of V1.

### 13.3 Legacy data

Existing Cases may be projected read-only for operators. The implementation must not infer a Story from matching URL/title without an approved migration mapping. New Archive contains only canonical finalized Articles unless a separate migration decision says otherwise.

## 14. Story metadata and New Development attention

Do not overload the public Story status tuple. Add narrow editor metadata:

```json
{
  "story_id": "s...",
  "followed": false,
  "last_reviewed_at": null,
  "reviewed_development_ids": []
}
```

- `followed` is a bookmark independent of review/ignored state.
- `reviewed_development_ids` acknowledges only the meaningful developments observed in the editor's current snapshot.
- Membership is ordered by `added_at`/item discovery time.
- `Прегледай` marks the submitted observed set reviewed without clearing `followed`.
- `Игнорирай` updates Story status and preserves `followed`, but an ignored Story never enters `Днес`, including for later developments.
- To restore an ignored Story, the editor opens it from `Истории → Игнорирани` and uses the existing `Прегледай` action. This clears ignored status and resumes normal follow/development semantics; no unignore action or state is added.
- Several unreviewed developments project as one Today entry with count and latest/relevant delta only when the Story is followed and not ignored.

If the closed `stories.json` schema must hold this metadata, bump and backward-normalize its schema. Never encode followed/reviewed-development meaning in `NEW/SEEN/IGNORED`.
### 14.1 Review snapshot contract

`Прегледай` acknowledges the developments the editor actually saw, not every development that exists when the command reaches the server:

```json
{
  "observedDevelopmentIds": ["dev_a", "dev_b"]
}
```

The server validates that the IDs belong to the Story, acknowledges only that observed set, updates the review timestamp/cursor, and preserves `followed`. A development arriving after the Story projection was loaded remains unreviewed and continues to project into `Днес` when the Story is followed and not ignored. Several observed developments are cleared by one command; no new state or action is created.




## 15. Research integration

### 15.1 Command

`POST /api/v1/stories/{storyId}/research`:

1. load the canonical Story and current `Какво липсва`;
2. call `readiness.expansion_plan()` (`readiness.py:645-668`);
3. call `search.run_search_operation()` with Story questions and strict constraints (`search.py:272-392`);
4. accept only opened sources through the research bundle contract;
5. preserve `DISCOVERY_ONLY` and claim-level provenance;
6. validate/merge Facts and Sources where possible;
7. re-assess gaps/readiness;
8. atomically update the same Story-owned basis;
9. return refreshed Story detail or plain-language failure.

### 15.2 Synchronous vs background-capable

Use a bounded operation runner: finish synchronously within the request budget; otherwise return `202 { operationToken }` and poll a transport-only endpoint. The UI shows only the existing loading/failure interaction. No research state, queue, or center is created. A minimal in-process registry is sufficient for local V1; process restart leaves gaps unchanged.

### 15.3 Failure semantics

No results, unavailable providers, blocked access, or invalid output must not remove verified facts, claim gaps resolved, or create editor state. Preserve `Какво липсва`, return short point-of-work feedback, and allow work to continue.

## 16. Draft-generation orchestration

### 16.1 Start Article

`POST /api/v1/stories/{storyId}/articles` validates the Story/action, creates an Article record with `story_id`, prefilled editable title, and proposed/empty focus, which projects as `Подготовка`. It persists lineage before any internal preparation and creates no visible Case or editor step.

### 16.2 One Draft command

`POST /api/v1/articles/{articleId}/draft` is the only editor-facing generation command. Internally it may create/resolve evidence, prepare generation inputs, call `live.live_readiness()` / `live.live_generate_draft()`, append an immutable generated Draft, and open an internal Case.

It must:

- re-evaluate focus and blocking gaps;
- fail with `BLOCKING_GAP` without generation when readiness fails;
- preserve Article/focus on provider failure;
- create no fabricated/empty Draft;
- project `Чернова` only when real text exists;
- return Article detail with warnings and next action.

The frontend never calls separate idea/evidence/prepared/case operations.

## 17. Manual Draft continuation

After AI failure the Article remains `Подготовка`. `Редактирай` is the secondary fallback and opens the same Article editor. The first server-confirmed non-empty body transitions it to `Чернова`, without `Напиши ръчно` or a new state.

The Case-only editor and current evidence-only `finalize()` refusal cannot represent this. Article finalization must accept manually created Article content while preserving safety/evidence checks.


## 18. Autosave and editing architecture

Store working title/body in an Article-keyed atomic JSON document. The Article record stores `content_version`; each confirmed save increments it. Keep the immutable generated Draft in the existing append-only store.

```text
PUT /api/v1/articles/{articleId}/content
{
  "expectedVersion": 7,
  "title": "...",
  "body": "..."
}
```

Server behavior:

- serialize mutation using shared application-level locking;
- reject mismatched version with 409;
- accept `Чернова`, or first manual text from `Подготовка`;
- atomically persist and return version/timestamp;
- never mutate the immutable generated Draft or finalize.

Frontend behavior:

- keep responsive local editor state;
- debounce approximately 800 ms after typing, with bounded flush on blur/navigation;
- show `Запазване…`, then `Запазено` only after confirmation;
- serialize saves per Article to prevent out-of-order writes;
- on network failure retain local text and show retryable feedback;
- on conflict preserve local text, fetch confirmed version, and require explicit resolution; never auto-merge.

No real-time collaboration or document lock is introduced. API and CLI mutation paths affecting the same store must share locking discipline.

## 19. Warning and validation handling

Warnings are projections of current audits, not Article state. They derive from deterministic lexical/semantic audits, originality, duplicate/provenance notes, and blocking safety failures. Preserve supporting fact/source references. Do not create a separate persisted warning entity merely for the UI.

`POST /ready` requires the current content version, re-runs current validation/warnings, rejects blocking issues, and records the exact `ready_version`, `ready_at`, and canonical warning/validation digest represented by `ready_validation_digest`. That digest is technical evidence of the validation set the editor reviewed, not a separate warning-acceptance workflow. `Готова` therefore binds to both the current content version and current validation result.

Any content edit after ready returns the Article to `Чернова` and invalidates readiness. The action is `Редактирай`; no extra confirmation action is introduced.

## 20. Finalization and Archive

`POST /finalize` requires `ready_version == content_version` and a current `ready_validation_digest`, non-empty title/body, no blocking safety failure, and valid Story lineage. It re-runs current validation/warnings. If content changed, the validation/warning set materially changed, or a new blocking issue appeared, it refuses without mutation and the Article no longer projects as `Готова`; the editor must explicitly use `Отбележи като готова` again for the new checkpoint. Non-blocking warnings are reviewed through the existing ready/finalize decision; there is no separate `Accept warnings` action.

It atomically records `finalized_at`, final title/body, Story, focus, and evidence references; preserves the immutable generated Draft; and excludes the Article from active lists. Existing Case finalization is used where applicable, but the canonical Article record is the editor-facing archive identity.

Archive returns finalized Articles only, newest first, with simple text search. It excludes old Cases, dry-runs, drafts, and CMS history. No publication integration is added.


## 21. `Днес` projection

`GET /api/v1/today` derives groups for new developments, new Stories, Articles needing action, and genuine problems.

Inclusion rules:

- Story `NEW` and not ignored → new unreviewed Story entry.
- followed and not ignored Story with meaningful development IDs after its review cursor → one entry with count and newest/relevant delta.
- `Подготовка` Article only when it has a concrete next action: focus, blocking gap, research, or Draft creation.
- `Чернова` Article only when current version needs editing/review.
- `Готова` Article only when finalization is next.
- operational problem only when failure has a clear consequence and action.

No attention flag, queue, or database record is persisted. Mutations invalidate/refetch the derived view.

`POST /today/refresh` composes collection and Story update sequentially under existing locks. It returns actionable failed-source problems; successful material is preserved. Collect/group stages remain invisible.

## 22. Component architecture

```text
app/
  AppShell, TopNavigation, QueryProvider, AppErrorBoundary
pages/
  TodayPage, StoryListPage, StoryWorkspace,
  ArticleListPage, ArticleWorkspace,
  ArchivePage, FinalizedArticleView, SettingsLanding
story/
  NewDevelopment, FactsAndSources, MissingInformation, StoryCorrection
articles/
  ArticleEditor, EditorialFocus, EvidenceRail,
  EditorialWarning, ArticleActions, AutosaveStatus
shared/
  StatusMarker, ActionGroup, SearchField,
  ListFilter, InlineFailure, LoadingIndicator
```

Page components own query/mutation orchestration; workspaces own disclosure/local editing. Reuse only boundaries with clear ownership. No generic entity renderer, workflow engine, or design-system exercise. Story Workspace links to related Article but never edits focus. Evidence stays secondary/collapsible.

## 23. Styling and visual-system implementation

### 23.1 CSS strategy

Use:

- one global stylesheet with CSS custom properties for frozen colors, type scale, spacing, borders/radii, and layout;
- CSS Modules for page/component scope;
- no Tailwind, CSS-in-JS, utility framework, or duplicated token package;
- no runtime CSS dependency.

Self-host Noto Sans/Noto Serif WOFF2 with full Cyrillic subsets and `font-display: swap`. Keep heading and UI font variables separate.

### 23.2 Layout primitives

Implement only frozen primitives:

- 64px top navigation;
- 1180px Today, 1080px Story, 1272px Article working width;
- 940px/32px/300px Draft/evidence geometry;
- collapsible evidence;
- frozen spacing/colors/warnings, 1px/3px rules, 4–6px radius, negligible shadow.

No additional breakpoints or mobile design are introduced.

## 24. Search, filtering, and ordering

- Stories: server-side case-insensitive text match over title, summary, and known terms; filters exactly `all/followed/developments/ignored`; latest meaningful change first.
- Articles: text match over title, related Story, and visible current text; filters exactly `all/preparation/draft/ready`; latest relevant update first.
- Archive: text match over title, Story, and final text; no filters; finalized date descending.
- Settings: no search/filter in V1.

At current file-store scale, load the small store and filter in the application service. Do not add a search engine. If measured scale later requires indexing, the API contract remains unchanged.

## 25. Migration plan

### Phase A — Contract and narrow model foundation

Phase A begins without React or any frontend work: first freeze the Article/Story metadata and DTO contracts, then implement their narrow stores, pure derived projections, and tests.

1. Freeze API DTO/error/action schemas as tests/contracts.
2. Add Article record/content stores and Story editor metadata.
3. Add pure projection services over existing stores.
4. Add API-level safety/transition tests before frontend cutover.
5. Leave legacy Workbench unchanged and operational.

Exit: canonical Article, Story lineage, three-state projection, and derived Today can be read without changing existing Case/domain behavior.

### Phase B — Vite/React shell and read-only views

1. Add `frontend/` Vite/React/strict TypeScript and lockfile.
2. Add React Router, TanStack Query, CSS tokens/modules, self-hosted fonts.
3. Configure Vite `/api` proxy.
4. Build shell, `Днес`, Stories list/detail, Article list read-only, Archive, Settings landing.
5. Serve compiled assets from Python in a development/integration mode.

Exit: frozen hierarchy and Editorial Desk render with real data; no mutations yet.

### Phase C — Story commands

1. Review/ignore using existing Story status.
2. Follow/unfollow and reviewed-development cursor.
3. Delta projection and one-entry multiple-development behavior.
4. Grouping correction.
5. `Обнови` orchestration and actionable problems.
6. Research execution and same-Story fact/gap update.

Exit: Story review, correction, and research acceptance scenarios pass.

### Phase D — Article preparation and generation

1. `Започни статия` creates Article in `Подготовка`.
2. Focus proposal/edit and readiness projection.
3. One `Направи чернова` command wrapping internal Idea/Evidence/Prepared/Case flow.
4. Manual `Редактирай` continuation after failure.

Exit: Story → Article → `Чернова` works without visible backend stages.

### Phase E — Editing, warnings, ready, finalization

1. Article-keyed revisioned autosave.
2. Conflict handling preserving local text.
3. Warning projection and local affected context.
4. `Отбележи като готова`, reopen-to-`Чернова`, and `Финализирай`.
5. Finalized Article Archive and traceability.

Exit: all approved Story/Article scenarios pass with rollback to legacy available.

### Phase F — Supporting surfaces and parity

1. Supporting lists/search/filter behavior.
2. Approved Settings landing and only then separately approved subpages.
3. API contract/integration/accessibility/visual-regression tests.
4. Remove old routes from primary navigation; retain measured rollback period.
5. Retire or isolate obsolete renderers only after parity and owner approval.

This is incremental and reversible. No big-bang replacement is required.


## 26. Parity and acceptance matrix

Risk scale: Low / Medium / High.

| Capability | Existing support | API work | Frontend work | Risk | Acceptance test |
|---|---|---|---|---|---|
| Today attention | Partial home/views | Derived projection + refresh | TodayPage | Medium | `followed AND not ignored AND unreviewed meaningful development`; only actionable canonical objects; no inventory/analytics. |
| Story review | Story status exists | Review command/observed-set contract | Story action | Low | Acknowledges only submitted observed IDs; newly arrived development remains in `Днес`; follow is unchanged. |
| Follow | Missing | Metadata + put/delete | Bookmark action | Low | Reviewed+followed reappears on unreviewed development; ignore/review never erase follow. |
| Ignore | Exists | Ignore command/projection | Story action | Low | Ignored+followed is absent from `Днес`, remains in `Игнорирани`; opening and `Прегледай` restore normal semantics. |
| New Development | Partial relation/reopen | Cursor/delta projection | Today/Story | High | A/B visible then C arrives → one `Прегледай` clears A/B only; C remains unreviewed. |
| Facts/Sources | Strong packet/provenance | Story projection | Newsroom notes | Medium | Verified source/locator inspectable; snippets never promoted. |
| Missing Information | Partial readiness | Blocking assessment | Inline section | Medium | Blocking gap blocks Draft; non-blocking stays visible. |
| Research More | Primitives, no executor | Story orchestration/operation | Inline load/error | High | Same-Story update; failure preserves gaps; no Research state. |
| Start Article | Lineage-losing bridge | Article command/store | Story→Article | High | Immediate `Подготовка` with Story/title/focus. |
| Editorial Focus | Internal suggestion | Canonical field/projection | Simple editor | Medium | 1–3 sentences; no angle/mode/voice quartet. |
| Draft readiness | Internal readiness | Server re-evaluation | Primary action | High | Invalid focus/blocking gap prevents generation. |
| Draft generation | Strong path | One orchestration command | Preparing state | High | One editor call; real text → `Чернова`; no fabricated Draft. |
| Manual continuation | Missing | Content command in preparation | `Редактирай` | High | Manual text transitions `Подготовка → Чернова`. |
| Editing/autosave | Case partial | Revision/conflict API | Local editor/autosave | High | Passive status; serialized saves; conflict preserves local. |
| Warnings | Strong audits | Stable projection/recheck | Local warning/evidence | High | Claim-linked severity; no workflow state. |
| Mark ready | Missing | Ready command/version | Explicit action | High | Current reviewed content becomes `Готова`; blocking refuses. |
| Reopen | Missing | Reopen transition | `Редактирай` | Medium | `Готова → Чернова`; checkpoint invalidated. |
| Finalize | Strong Case contract | Article finalization/lineage | Finalize/Archive | High | Ready/current version required; immutable; no publish. |
| Archive | Mixed finalized Cases | Finalized Article list/detail | Archive | Medium | Only canonical finalized Articles, newest first. |
| Grouping correction | Exists | Secondary commands | Disclosure | Low | Works without becoming primary. |
| Settings boundaries | Strong stores | Technical projections | Future subpages | Low | No routes/traces/secrets in editor DTOs. |
| Ingestion/refresh | Strong mechanisms | Refresh/inputs boundary | Today/Settings | Medium | `Обнови` hides stages; only consequences surface. |

Existing guarantees to preserve in API tests include immutable Draft/working-copy separation, stale finalization refusal, finalized-save refusal, closed Idea non-revival, refusal-without-mutation, provider-failure-never-merges, and official provenance for council claims. These are covered today in `tests/test_workbench.py`, `test_workbench_articles.py`, `test_workbench_newsroom.py`, `test_story_identity.py`, and `test_workflow_research.py`.

Focused architecture inspection verification: **238 relevant existing tests passed**.


## 27. Security and data integrity

- Keep localhost binding by default; no public exposure in this migration.
- No new auth/roles system. Non-local deployment requires a separate security milestone.
- Same-origin API; no permissive CORS.
- Validate JSON type, size, IDs, enums, text length, and URLs server-side.
- Never accept filesystem paths, store keys, provider routes, or arbitrary query expressions.
- Re-check Story/Article ownership and state for every command.
- Serialize before atomic publish; never truncate a valid store.
- Share mutation locks across API and CLI paths.

Autosave integrity:

- monotonic `content_version` and expected-version check;
- no out-of-order saves;
- conflict retains client text and never auto-merges;
- AI base ID remains in Article metadata;
- save never finalizes or changes evidence/readiness.

Source/evidence integrity:

- snippets remain discovery-only;
- only opened promotable sources support facts;
- claim locators remain attached;
- blocked publishers/sources never become verified evidence;
- failure does not silently remove/downgrade verified data.

Generation/finalization integrity:

- readiness and safety gates remain server-authoritative;
- failure creates no Draft/Case/text;
- blocking factual/safety issues cannot be ready/finalized;
- finalization is explicit, not publication;
- finalized content is immutable.

## 28. True backend gaps and smallest obligations

### Already exists

Strict Story/publication identity; chronology and correction; collection/source health; search/page opening; research/provenance/duplicate safeguards; readiness; immutable Draft generation/audits/originality/routing/quotas; Case working copy/stale protection/finalization; YouTube intake/diagnostics.

### Exists but needs adapter/projection

Home → Today; Story cards/detail → Story projections; Publications/chronology → Story Workspace; evidence/readiness/warnings → Facts/Gaps/Warnings; Case/working copy → Article Workspace; settings/intake/diagnostics → Settings; form actions → JSON commands.

### Partial capability

1. **New Development** — classification/reopen exists; meaningful delta/review cursor/follow recall is incomplete.
2. **Research** — primitives exist, but no Story executor writes results back.
3. **Readiness** — internal assessment exists; focus/blocking projection and one editor command do not.
4. **Warnings** — audits exist; stable identity/range and recheck-after-edit need projection.
5. **Finalization** — Case finalization exists; Article ready/reopen/manual semantics do not.

### Missing implementation

1. **First-class Story–Article lineage.** `promote_story_to_idea()` (`workbench/state.py:1222-1300`) drops `story_id`; add one Article record store.
2. **Follow/bookmark and reviewed-development cursor.** Add narrow Story metadata.
3. **Manual Draft continuation.** Add Article content/finalization path.
4. **Explicit `Готова` checkpoint and reopen transition.** Persist `ready_version`, `ready_at`, and `ready_validation_digest`; revalidate on finalize.
5. **JSON API/application projections.** Add same-origin adapter while preserving legacy routes.

No relationship graph, workflow engine, event bus, database migration, or microservice is required.


## 29. Principal risks

| Risk | Mitigation |
|---|---|
| Article appears to duplicate Case | Article is canonical editor identity/working content; Case/Draft remain immutable generation/provenance artifacts. |
| File-store concurrency | Shared mutation coordinator plus optimistic content versions. |
| Cross-store partial transaction | Ordered idempotent writes; Article state changes last; crash-point tests; repair from immutable refs. |
| Long research/generation | Bounded operation runner and idempotent command identity; no editor status. |
| Warning drift after edits | Revalidate on ready/finalize; project current-version warnings. |
| Legacy data lacks lineage | Keep operator-only; explicit migration; never infer silently. |
| Story delta quality | Conservative meaningfulness assessment, evidence, correction tools, real-material regression corpus. |
| Settings scope creep | Landing only; separately approve subpages. |
| Dual UI drift | Route old/new actions through shared application services before cutover. |

### 29.1 Cross-store write strategy

`Направи чернова` and finalization touch multiple stores. V1 does not need a database transaction:

1. use stable/idempotent Article command identity;
2. validate all preconditions before generation;
3. append immutable generated artifacts only after parsing/audit success;
4. atomically update Article metadata last;
5. if metadata write fails, report incomplete/failure without fabricated text and reconcile from internal IDs;
6. test crash points.

The API must not report `Чернова`/finalized until canonical Article metadata and required content are durably written.

## 30. Recommended implementation sequence

1. Freeze the approved Article/Story metadata and DTO contracts.
2. Add Article record/content stores and Story editor metadata with safe readers.
3. Implement pure projections and validation tests without HTTP/UI.
4. Add application commands/queries; route legacy actions through them where practical.
5. Add `/api/v1` adapter and API contract tests.
6. Build Vite/React shell and read-only centerpiece surfaces.
7. Add Story review/follow/development/grouping commands.
8. Add `Обнови` and research execution.
9. Add Article start/focus/readiness/generation/manual continuation.
10. Add autosave/conflicts/warnings/ready/reopen/finalize/Archive.
11. Add supporting lists and Settings landing.
12. Run parity, accessibility, visual-regression, and real-material Story tests.
13. Remove legacy primary navigation, retain rollback, then separately approve retirement.

Implementation may begin with Phase A and remains subject to the migration gates below. No sequence item reopens frozen UX decisions, and later phases do not begin before their stated exit criteria pass.

## 31. Final architecture gate

This design preserves:

- exactly five primary areas: `Днес / Истории / Статии / Архив / Настройки`; no sixth area;
- exactly three active editor Article states: `Подготовка / Чернова / Готова`; Archive is the finalized surface, not a fourth state;
- frozen vocabulary, actions, workflows, ownership, and routes, with no new editor action or workflow;
- the canonical `Редакционен фокус`, while angle, mode, and voice remain internal or secondary implementation concepts;
- `Днес` as derived attention, with no attention persistence;
- no raw Publications queue or Research center;
- no manual intake, publishing, notifications, assignments, analytics, or frontend exposure of Idea/EvidencePacket/Prepared/Case/model/provider internals;
- AI as invisible supporting infrastructure;
- mature Python domain/safety authority and no new backend framework;
- incremental, reversible strangler migration and legacy rollback;
- all frozen UX and visual specifications unchanged by this implementation contract.

**Approval:** `owner-approved implementation architecture — frozen`.

**Next implementation step:** Phase A, `Contract and narrow model foundation`, without React. After its contracts, stores, derived projections, and tests pass the stated exit criteria, the sequence may proceed to the API and frontend phases. This document does not authorize UX redesign or scope expansion.
