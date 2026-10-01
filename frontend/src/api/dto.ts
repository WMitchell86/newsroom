export type AvailableAction =
  | "REVIEW"
  | "FOLLOW"
  | "UNFOLLOW"
  | "IGNORE"
  | "RESEARCH_MORE"
  | "START_ARTICLE"
  | "SELECT_FOCUS"
  | "CHANGE_FOCUS"
  | "MAKE_DRAFT"
  | "EDIT"
  | "MARK_READY"
  | "FINALIZE"
  // V1.2-G4.3 §D/§E: the two secondary writing controls, offered on a real Draft
  // and never as a next action. `REWRITE` is `Пренапиши`; `CHANGE_VOICE` is the
  // optional `Стил` choice. Neither is a state.
  | "REWRITE"
  | "CHANGE_VOICE"
  // V1.1-D2: the one Today fast-triage command. It exists only on a Today
  // Story row; the Story and Article workspaces keep their explicit actions.
  | "QUICK_DRAFT";

export interface NextAction {
  action: AvailableAction;
  reasonCode: string;
  label: string;
  primary: boolean;
}

export interface Warning {
  id: string;
  severity: "info" | "review" | "blocking";
  message: string;
  affectedText?: string;
  range?: { start: number; end: number };
  evidenceRefs?: Array<{ publicationId?: string; sourceId?: string; locator?: string }>;
  blocking: boolean;
}

export interface Source {
  id: string;
  name: string;
  domain?: string;
  url?: string;
  locator?: string;
}

export interface FactAndSource {
  id: string;
  text: string;
  source: Source;
  locator?: string;
  scope: "current" | "background";
}

export interface MissingInformationItem {
  id: string;
  question: string;
  kind: "missing_fact" | "conflict" | "unresolved";
  blocking: boolean;
  reason?: string;
}

/**
 * V1.2-G4.1 §B3: a publication that was really opened, with the authority the
 * editor configured for it. Present so the editor can see what a Draft would be
 * written from — which is the whole point of warning instead of refusing.
 */
export interface OpenedSource {
  id: string;
  name: string;
  url: string;
  domain: string;
  /** G4: `Надежден за факти` is the only authority in the product. */
  factualAuthority: boolean;
  authority: "PRIMARY" | "CORROBORATING";
}

export interface MissingInformation {
  items: MissingInformationItem[];
  assessedAt: string | null;
  /** V1.1-A: absent basis is UNASSESSED, never an empty assessed state. */
  evidenceStatus?: "unassessed" | "assessed";
  /** V1.2-G4.1 §B3: always present; empty when nothing was ever opened. */
  openedSources?: OpenedSource[];
}

export interface NewDevelopment {
  id: string;
  publicationId: string;
  title: string;
  summary: string;
  changedAt: string;
  unreviewed: boolean;
}

export interface ArticleReference {
  id: string;
  title?: string;
  updatedAt?: string;
  /** Present once the Article is finalized: the link then targets the Archive. */
  finalizedAt?: string | null;
  /**
   * V1.2-G2: the canonical state word, from the same
   * `derive_article_state` decision the Article workspace and Today read. It is
   * `null` for a finalized Article, which has left the active workflow, and
   * absent on a projection written before this field existed — never a state
   * guessed in its place.
   */
  state?: ArticleState | null;
}

export interface Publication {
  id: string;
  title: string;
  source: { id: string; name: string; domain?: string };
  url: string;
  publishedAt: string | null;
  discoveredAt: string;
  summary: string;
  factsAndSourceIds: string[];
}

export interface StoryEvent {
  publicationId: string;
  at: string;
  kind: "NEW_DEVELOPMENT" | "EVENT";
  title: string;
}

export interface StorySummary {
  id: string;
  title: string;
  summary: string;
  reviewed: boolean;
  ignored: boolean;
  followed: boolean;
  hasNewDevelopment: boolean;
  unreviewedDevelopmentCount: number;
  latestDevelopment: NewDevelopment | null;
  latestChangeAt: string;
  availableActions: AvailableAction[];
  nextAction: NextAction | null;
}

export interface StoryDetail extends StorySummary {
  whatHappened: string;
  publications: Publication[];
  chronology: StoryEvent[];
  newDevelopments: NewDevelopment[];
  relatedArticles: ArticleReference[];
  factsAndSources: FactAndSource[];
  missingInformation: MissingInformation;
  /**
   * V1.2-G2: the number of **independent publishers** behind this Story,
   * surfaced from the `story_store.metrics` computation the system already uses
   * for Today. It is corroboration context, never evidence authority: a Story
   * can have five publishers and still have no opened, promotable page. `null`
   * means the members carry no publisher identity — unknown, not a measured
   * zero — and the UI must not print the zero.
   */
  publisherCount?: number | null;
  /**
   * V1.2-G2.2 §9: the id of the grouped publication that IS the original
   * (the Story's canonical representative). It is what makes `Отвори
   * оригинала` possible without React reconstructing a URL or guessing which
   * member came first. `null` when the Story has no representative publication.
   */
  originPublicationId?: string | null;
  correction: {
    available: boolean;
    actions: Array<"DETACH_PUBLICATION" | "MERGE_STORY">;
  };
}

export type ArticleState = "preparation" | "draft" | "ready";

export interface EditorialFocus {
  text: string;
  confirmedAt: string | null;
}

export interface ArticleContent {
  title: string;
  body: string;
  version: number;
}

/** Backend-derived currency of the current-content validation (C4). */
export interface ArticleValidation {
  contentVersion: number;
  current: boolean;
  blocking: boolean;
  readyEligible: boolean;
}

/**
 * V1.1-B: the one canonical Draft-readiness reason, decided by the backend.
 * `code` is the stable contract; `message` is the exact editor wording. React
 * renders both verbatim and never derives eligibility from local state.
 */
export type DraftReadinessCode =
  | "DRAFT_ELIGIBLE"
  // V1.2-G4.4: the Story's own publication is worth one bounded read, so a
  // Draft is worth ATTEMPTING - but nothing is read or confirmed yet.
  | "DRAFT_FROM_UNREAD_SOURCE"
  | "FOCUS_NOT_CONFIRMED"
  | "STORY_UNASSESSED"
  // V1.2-G4.1 §B6: the ONE real Draft blocker — there is genuinely nothing to
  // write from. `BLOCKING_GAP` / `NO_CONFIRMED_FACTS` / `NO_OPEN_SOURCE` are gone:
  // an open question is a warning on the Draft, not a refusal to start it.
  | "NO_DRAFT_MATERIAL"
  | "NOT_IN_PREPARATION"
  | "STORY_UNAVAILABLE"
  // V1.2-G2.2 §3: research was refused for an OPERATIONAL reason. These are
  // deliberately not evidence reasons: the editor is told the capability is
  // unavailable or its bounded budget is spent, never that a source is missing.
  | "RESEARCH_UNAVAILABLE"
  | "RESEARCH_QUOTA_EXHAUSTED"
  // §R4: these branches used to collapse into one generic sentence. Each names a
  // real, distinguishable outcome: no page opened / opened but not confirmed /
  // a genuine technical interruption.
  | "RESEARCH_NO_SOURCE"
  | "RESEARCH_NOT_CONFIRMED"
  | "RESEARCH_NOT_APPLICABLE"
  | "RESEARCH_INTERRUPTED"
  | "ARTICLE_HAS_TEXT"
  | "SAFETY_BLOCKED"
  | "ARTICLE_VERSION_CONFLICT"
  | "WORKING_TITLE_REQUIRED";

export interface DraftReadiness {
  code: DraftReadinessCode;
  message: string;
}

/**
 * V1.1-C: the durable generation failure that makes manual continuation a
 * legitimate recovery path. `reasonCode` is the stable editor-safe class; it is
 * never a provider error, a model name or a path.
 */
export type DraftFailureCode = "PROVIDER_UNAVAILABLE" | "GENERATION_FAILED";

export interface DraftFailure {
  reasonCode: DraftFailureCode;
  failedAt: string;
}

export interface PreparationProjection {
  focusConfirmed: boolean;
  /**
   * §D2: two or three quiet Focus alternatives, derived deterministically by the
   * backend. Clicking one replaces the field text and saves it; there is no
   * Apply, Confirm or modal. An empty list is a normal outcome and never blocks
   * a Draft.
   */
  focusAlternatives: string[];
  blockingGaps: MissingInformationItem[];
  nonBlockingGaps: MissingInformationItem[];
  draftEligible: boolean;
  /**
   * The single readiness explanation. There is exactly one, so the page can
   * never render a green line beside a blocking one.
   */
  draftReadiness: DraftReadiness;
  /**
   * V1.1-C: null unless an eligible generation genuinely failed on this exact
   * basis. `availableActions` carries `EDIT` precisely when this is non-null, so
   * the page never derives the recovery path from its own local state.
   */
  draftFailure: DraftFailure | null;
  availableActions: AvailableAction[];
}

/**
 * V1.2-G4.3 §D — the optional Voice control, as the backend sends it.
 *
 * `voice` is `""` for `Автоматично`, which is the default and the common case.
 * `options` is the complete set the editor may choose from and comes from the
 * same canonical list the style system consumes, so the UI can never offer a
 * voice the writer could not honour.
 */
export interface ArticleStyle {
  voice: string;
  label: string;
  options: { id: string; label: string; description: string }[];
}

export interface ArticleProjection {
  id: string;
  title: string;
  story: ArticleReference;
  state: ArticleState | null;
  editorialFocus: EditorialFocus;
  style: ArticleStyle;
  content: ArticleContent;
  preparation: PreparationProjection | null;
  readiness: {
    isCurrent: boolean;
    readyVersion: number | null;
    readyAt: string | null;
  };
  warnings: Warning[];
  validation: ArticleValidation;
  availableActions: AvailableAction[];
  nextAction: NextAction | null;
  createdAt: string;
  updatedAt: string;
  isFinalized: boolean;
  finalizedAt: string | null;
  factsAndSources: FactAndSource[];
  missingInformation: MissingInformation;
  /**
   * V1.2-G4.1 §B3/§C2 — the warnings a Draft carries because of the material it
   * was written from (e.g. one unconfirmed source). Recomputed by the backend
   * from the canonical basis on every read, so they can never go stale. These
   * are warnings, never a state: the Article is still `Чернова`.
   */
  draftWarnings: string[];
}

export interface ArticleSummary extends ArticleProjection {
  state: ArticleState;
  isFinalized: false;
  finalizedAt: null;
}

export type ArticleDetail = ArticleProjection;

export interface ArchiveSummary {
  id: string;
  title: string;
  story: ArticleReference;
  finalizedAt: string;
}

export interface ArchiveArticle extends ArticleProjection {
  state: null;
  isFinalized: true;
  finalizedAt: string;
  availableActions: [];
  nextAction: null;
}

interface AttentionBase {
  objectId: string;
  title: string;
  summary: string;
  timestamp: string;
}

/**
 * D2: the narrow Quick Draft state for one Today Story row.
 *
 * The backend decides availability and the label; the client renders them and
 * derives nothing. `articleId` is present when a unique active Article already
 * exists, which is what lets the row say «Отвори чернова» instead of creating a
 * second one.
 */
export interface TodayQuickDraft {
  available: boolean;
  label: string;
  articleId: string | null;
  /** Why the row withholds the button; `null` when it is offered. */
  reasonCode: string | null;
  /**
   * V1.2-G4.6: a Quick Draft is already running for this Story.
   *
   * The pending state used to live only in React, so it vanished the moment the
   * editor navigated away and the row offered «Чернова» again over work that was
   * still running. The server owns that fact, so the server says it.
   */
  inFlight: boolean;
  /**
   * V1.2-G4.6: the last Quick Draft this editor asked for, and how it ended.
   *
   * A failed attempt leaves no Article to open, so this is the only place the
   * outcome can surface. `null` means they have not tried, which is different
   * from `status: "failed"` and must not look the same.
   */
  lastAttempt: {
    status: "pending" | "running" | "succeeded" | "failed";
    errorCode: string;
    error: string;
  } | null;
}

/**
 * V1.2-G4.6: one entry in the editor's own operation history.
 *
 * This exists because asking for a Draft returned an opaque 202 handle and
 * nothing else. There was no list, so "what happened to the four I started"
 * had no answer anywhere in the product. The server decides every field; the
 * client renders and derives nothing.
 */
export interface OperationSummary {
  operationToken: string;
  /** The scope the work was requested for, e.g. `article-draft:art_...`. */
  storyId: string;
  status: "pending" | "running" | "succeeded" | "failed";
  /** Stable code, or "" while nothing has gone wrong. */
  errorCode: string;
  /** The server's own recorded reason, already sanitized server-side. */
  error: string;
  /**
   * V1.2-G4.36: what the **command** did, which is not the same question as
   * what the worker did.
   *
   * `status` reports that the worker returned. A Quick Draft that ran to
   * completion and produced nothing returns `needs_attention` — a refusal —
   * while `status` stays `succeeded`, so this page used to label it «Готово»
   * with no reason at all. That is the surface an editor uses to ask "what
   * happened to the four I started", and it was answering `succeeded` for
   * work that had produced nothing.
   *
   * Empty when the command reported no outcome of its own.
   */
  outcome: string;
  /** The command's own stable refusal code, when it refused. */
  outcomeCode?: string;
  /** The command's own editor sentence for that refusal. */
  outcomeMessage?: string;
}

export type TodayAttention =
  | (AttentionBase & {
      objectType: "story";
      reason: "NEW_STORY" | "UNREVIEWED_DEVELOPMENT";
      nextAction: "REVIEW";
      delta: { unreviewedDevelopmentCount: number };
      /**
       * V1.2-G1 §10: how many **independent publishers** the Story has.
       *
       * Computed by the backend, never in React. It is publication/corroboration
       * context only — it is NOT a claim that any of those pages was opened, and
       * it must never be rendered as a trust or verification badge.
       */
      publisherCount?: number;
      /**
       * V1.2-G4.5: where this Story's material actually came from.
       *
       * `publisherCount` answers "how many said it", which names nobody and
       * opens nothing. These two answer "who, and take me there" — the
       * representative publication's own URL, and the operator's name for that
       * source when the registry has one (otherwise its host, which is a fact
       * rather than a guess about who published it).
       *
       * Both are empty when the representative carries no URL, and the row then
       * prints no source at all rather than a plausible-looking one.
       */
      sourceUrl?: string;
      sourceName?: string;
      /**
       * V1.2-G1 §13: the reserved editorial-category slot.
       *
       * Current Stories have **no** production category: `category` is not part
       * of the canonical Story schema. This field is therefore absent on every
       * real row today, and the row renders nothing for it. It exists so the
       * visual contract is validated now and the category slice can populate it
       * later, without relaying out the desk. It must stay `undefined` until
       * the backend genuinely classifies Stories — no keyword heuristics, no
       * source-kind inference, no shadow-model output.
       */
      category?: string;
      /** `REVIEW` keeps its existing meaning; `QUICK_DRAFT` is backend-gated. */
      availableActions: AvailableAction[];
      quickDraft: TodayQuickDraft;
    })
  | (AttentionBase & {
      objectType: "article";
      reason: "PREPARATION" | "DRAFT" | "READY";
      nextAction: NextAction;
    });

/** D2: the only three outcomes a Quick Draft can report. */
export type QuickDraftStatus = "draft_created" | "existing_article" | "needs_attention";

/**
 * D2: the operation result. Deliberately narrow — no Case id, no EvidencePacket
 * id, no provider, no search internals and no model id ever cross here.
 */
export interface QuickDraftResult {
  status: QuickDraftStatus;
  /** Present whenever a real Article is the destination. */
  articleId?: string;
  storyId?: string;
  reasonCode?: string;
  message?: string;
}

export interface TodayProblem {
  id: string;
  title: string;
  consequence: string;
  label: string;
  target: string;
}

/**
 * D1: the last completed newsroom run, as Today needs to describe it.
 *
 * This is a projection of the existing `last_run.json`, not the file itself:
 * per-source problem detail, blocked/duplicate counts and source ids stay in
 * the operational store and never cross into the editor's first screen.
 */
export interface LastRefresh {
  /** ISO-8601 UTC instant the run finished; rendered in Europe/Sofia. */
  finishedAt: string;
  newPublications: number;
  /**
   * `null` when the run predates this field. An absent count is honest; a
   * fabricated `0` would be a claim the store cannot support.
   */
  newStories: number | null;
  failedSources: number;
}

/**
 * Story-grouping health for the latest run (V1.1-F2A).
 *
 * `null` means **unknown** — the run predates this field. The UI must treat
 * that as "no warning": a run that never reported grouping health cannot be
 * claimed to have been unhealthy.
 *
 * `healthy` and `unknown` are both silent. Only a real degradation is surfaced,
 * because permanent status chrome would train the editor to ignore the surface.
 */
export type GroupingHealthStatus =
  | "healthy"
  | "degraded"
  | "budget_exhausted"
  | "unavailable";

/**
 * V1.2-G4.5. One model's routing health inside a role.
 *
 * `eligible < total` is normal — a paid route on a free policy is ineligible
 * by design. Only `eligible === 0` is a problem, because a role with no
 * routable path does not fail, it silently does less.
 */
export interface RoleHealth {
  role: string;
  eligible: number;
  total: number;
  /**
   * What the role does when it cannot route: `fail_visible`, `review_required`,
   * `degraded`, `conservative`, `deterministic`, `cheap_only`,
   * `distinguish_zero`. The backend's own word — never derived here.
   */
  onExhausted: string;
}

export interface GroupingHealth {
  status: GroupingHealthStatus;
  /** ISO-8601 UTC instant of the last successful semantic classification. */
  lastSuccessfulSemanticClassificationAt: string | null;
  /** Publications that reached the anchored shortlist and needed a decision. */
  semanticRequired: number;
  semanticAnswered: number;
  /**
   * Publications kept separate because classification could not be completed.
   * This is a measure of quality loss, not of traffic.
   */
  semanticDegraded: number;
}

/**
 * V1.2-G4.1 §A4 — the desk scope. `region` is the Burgas working desk (the
 * default); `all` shows the whole horizon. Nothing is ever deleted: «Истории»
 * always reaches every collected Story.
 */
export type TodayScope = "region" | "all";

export interface TodayProjection {
  /** `null` means no run has ever happened — not "ran with nothing to show". */
  lastRefresh: LastRefresh | null;
  /** V1.2-G4.1 §A4: the scope this projection was actually built with. */
  scope: TodayScope;
  /** `null` when the latest run predates grouping-health reporting. */
  groupingHealth: GroupingHealth | null;
  /**
   * V1.2-G4.22 — the per-ROLE `roleHealth` field that used to sit here was
   * REMOVED from this projection, and the note replaces it so nobody re-adds
   * it by assumption.
   *
   * Role health comes from its own endpoint (`getRoleHealth`, query key
   * ["role-health"]) and `TodayHeader` renders from that query, not from the
   * projection. The server has never sent the field here.
   *
   * It was also declared with the wrong shape even for the value that does
   * exist: the header expects
   *   { ok, roles, unroutableRoles, remedy } | null
   * and this said `RoleHealth[]` — an array. A field that is never returned,
   * carrying a type that contradicts its only real consumer, is what the next
   * person wires up by mistake.
   */
  /** Every Story that qualifies as current, before the cap. */
  storyAttentionTotal: number;
  /** How many of those the cap actually lets through. */
  storyAttentionShown: number;
  newDevelopments: TodayAttention[];
  newStories: TodayAttention[];
  articlesRequiringAction: TodayAttention[];
  problems: TodayProblem[];
}

export type ApiErrorCode =
  | "VALIDATION_ERROR"
  | "NOT_FOUND"
  | "INVALID_TRANSITION"
  | "ARTICLE_VERSION_CONFLICT"
  | "BLOCKING_GAP"
  // V1.1-B: the evidence-remedy reasons stay distinct end to end.
  | "STORY_UNASSESSED"
  | "NO_DRAFT_MATERIAL"
  | "FOCUS_NOT_CONFIRMED"
  | "NOT_IN_PREPARATION"
  | "STORY_UNAVAILABLE"
  // V1.2-G2.2 §3: research was refused for an OPERATIONAL reason. These are
  // deliberately not evidence reasons: the editor is told the capability is
  // unavailable or its bounded budget is spent, never that a source is missing.
  | "RESEARCH_UNAVAILABLE"
  | "RESEARCH_QUOTA_EXHAUSTED"
  // §R4: these branches used to collapse into one generic sentence. Each names a
  // real, distinguishable outcome for the editor.
  | "RESEARCH_NO_SOURCE"
  | "RESEARCH_NOT_CONFIRMED"
  | "RESEARCH_NOT_APPLICABLE"
  | "RESEARCH_INTERRUPTED"
  | "ARTICLE_HAS_TEXT"
  | "WORKING_TITLE_REQUIRED"
  | "SAFETY_BLOCKED"
  | "SOURCE_UNAVAILABLE"
  // V1.2-G4.5. The server may name a reason this build predates, and that must
  // survive the trip: dropping it is what turned `NO_DRAFT_MATERIAL` and
  // `PROVIDER_UNAVAILABLE` into "Вътрешна грешка" for the editor. `string & {}`
  // keeps every literal above available to autocomplete while admitting the
  // rest, so adding a reason on the server no longer requires a matching edit
  // here before it can be read.
  | (string & {})
  | "INTERNAL_ERROR";

export interface ApiErrorEnvelope {
  error: {
    code: ApiErrorCode;
    message: string;
    retryable: boolean;
    fieldErrors: Array<{ field: string }>;
  };
}

/**
 * V1.2-G4 §12/§13: the canonical registry enums, unchanged.
 *
 * These are the *stored* values. The screen renders `kindLabel` / `priorityLabel`
 * and filters on these, so the editor never reads a registry word but the client
 * still compares against the real vocabulary instead of parsing a label.
 */
export type SourceKind = "official" | "media" | "national" | "regional" | "aggregator";
export type SourcePriority = "high" | "normal" | "low";

/** One source row, in the words the newsroom uses. */
export interface SourceRow {
  /** The immutable `source_id`. Never editable, so history stays interpretable. */
  id: string;
  name: string;
  kind: SourceKind;
  kindLabel: string;
  domain: string;
  /** The feed URL, or what the monitoring query watches. */
  address: string;
  /** §8: the *effective* status, so an expired mute reads as monitored again. */
  monitored: boolean;
  muteUntil: string;
  /** §6: the editor's own claim-appropriateness policy for this publisher. */
  factualAuthority: boolean;
  priority: SourcePriority;
  priorityLabel: string;
  note: string;
  /** §15: a quiet status. No HTTP error, no collector internals. */
  health: { status: "working" | "problem" | "unknown"; label: string; lastSuccessAt: string };
}

export interface SourceSummary {
  total: number;
  monitored: number;
  notMonitored: number;
  factualAuthority: number;
  problems: number;
}

export interface SourcesProjection {
  sources: SourceRow[];
  summary: SourceSummary;
}

/** §9: the six things the add form asks for. Everything else is derived. */
export interface NewSourceInput {
  name: string;
  address: string;
  kind: SourceKind;
  monitored: boolean;
  factualAuthority: boolean;
  priority: SourcePriority;
}

/** §10: the closed set of fields a row may be changed on. */
export interface SourceChanges {
  name?: string;
  monitored?: boolean;
  factualAuthority?: boolean;
  priority?: SourcePriority;
}

/**
 * V1.2-G4.3 §G — the controlled learning loop, as Settings sees it.
 *
 * The backend is the authority on every field. `proposals` is empty until the
 * threshold is reached, so this screen can never offer a decision the service
 * would refuse; `instructions` is the set a human has actually decided on.
 */
export interface FeedbackProposal {
  patternId: string;
  label: string;
  target: string;
  support: number;
  total: number;
  examples: string[];
  suggestedInstruction: string;
  /** `conflict` is a question to the editor, never an approvable rule. */
  status: "proposed" | "conflict";
}

export interface FeedbackInstruction {
  patternId: string;
  target: string;
  instruction: string;
  support: number;
  approved: boolean;
  decidedAt: string;
}

export interface FeedbackStatus {
  pending: number;
  threshold: number;
  eligible: boolean;
  proposals: FeedbackProposal[];
  instructions: FeedbackInstruction[];
}

/** The decided entry, plus the whole new state it produced. */
export interface FeedbackDecisionResult extends FeedbackStatus {
  decision: FeedbackInstruction;
}
