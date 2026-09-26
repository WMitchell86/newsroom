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

export interface MissingInformation {
  items: MissingInformationItem[];
  assessedAt: string | null;
  /** V1.1-A: absent basis is UNASSESSED, never an empty assessed state. */
  evidenceStatus?: "unassessed" | "assessed";
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
  | "FOCUS_NOT_CONFIRMED"
  | "STORY_UNASSESSED"
  | "NO_CONFIRMED_FACTS"
  | "NO_OPEN_SOURCE"
  | "BLOCKING_GAP"
  | "NOT_IN_PREPARATION"
  | "STORY_UNAVAILABLE"
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

export interface ArticleProjection {
  id: string;
  title: string;
  story: ArticleReference;
  state: ArticleState | null;
  editorialFocus: EditorialFocus;
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

export interface TodayProjection {
  /** `null` means no run has ever happened — not "ran with nothing to show". */
  lastRefresh: LastRefresh | null;
  /** `null` when the latest run predates grouping-health reporting. */
  groupingHealth: GroupingHealth | null;
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
  | "NO_CONFIRMED_FACTS"
  | "NO_OPEN_SOURCE"
  | "FOCUS_NOT_CONFIRMED"
  | "NOT_IN_PREPARATION"
  | "STORY_UNAVAILABLE"
  | "ARTICLE_HAS_TEXT"
  | "WORKING_TITLE_REQUIRED"
  | "SAFETY_BLOCKED"
  | "SOURCE_UNAVAILABLE"
  | "INTERNAL_ERROR";

export interface ApiErrorEnvelope {
  error: {
    code: ApiErrorCode;
    message: string;
    retryable: boolean;
    fieldErrors: Array<{ field: string }>;
  };
}
