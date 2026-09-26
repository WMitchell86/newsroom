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
  | "FINALIZE";

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

export interface PreparationProjection {
  focusConfirmed: boolean;
  blockingGaps: MissingInformationItem[];
  nonBlockingGaps: MissingInformationItem[];
  draftEligible: boolean;
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

export type TodayAttention =
  | (AttentionBase & {
      objectType: "story";
      reason: "NEW_STORY" | "UNREVIEWED_DEVELOPMENT";
      nextAction: "REVIEW";
      delta: { unreviewedDevelopmentCount: number };
    })
  | (AttentionBase & {
      objectType: "article";
      reason: "PREPARATION" | "DRAFT" | "READY";
      nextAction: NextAction;
    });

export interface TodayProblem {
  id: string;
  title: string;
  consequence: string;
  label: string;
  target: string;
}

export interface TodayProjection {
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
