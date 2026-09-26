import type {
  ApiErrorCode,
  ArchiveArticle,
  ArticleDetail,
  ArticleSummary,
  QuickDraftResult,
  StoryDetail,
  TodayProjection,
} from "./dto";

/** The canonical result of `Финализирай`: the frozen Article and where it lives. */
export interface FinalizeResult {
  articleId: string;
  archivePath: string;
  finalizedAt: string;
  article: ArchiveArticle;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode | "NETWORK_ERROR";
  readonly retryable: boolean;

  constructor(
    status: number,
    code: ApiErrorCode | "NETWORK_ERROR",
    message: string,
    retryable: boolean,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

const apiErrorCodes: ReadonlySet<string> = new Set([
  "VALIDATION_ERROR",
  "NOT_FOUND",
  "INVALID_TRANSITION",
  "ARTICLE_VERSION_CONFLICT",
  "BLOCKING_GAP",
  "SAFETY_BLOCKED",
  "SOURCE_UNAVAILABLE",
  "INTERNAL_ERROR",
]);

function parseFailure(status: number, value: unknown): ApiError {
  if (isRecord(value) && isRecord(value.error)) {
    const candidate = value.error;
    if (
      typeof candidate.code === "string" &&
      apiErrorCodes.has(candidate.code) &&
      typeof candidate.message === "string" &&
      typeof candidate.retryable === "boolean" &&
      Array.isArray(candidate.fieldErrors) &&
      candidate.fieldErrors.every((field) => isRecord(field) && typeof field.field === "string")
    ) {
      return new ApiError(
        status,
        candidate.code as ApiErrorCode,
        candidate.message,
        candidate.retryable,
      );
    }
  }
  return new ApiError(status, "INTERNAL_ERROR", "Вътрешна грешка. Опитайте отново.", true);
}

export function createIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `research-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

async function sendStoryCommand<T>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(extraHeaders ?? {}),
      },
      credentials: "same-origin",
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Връзката с редакционната система е прекъсната.", true);
  }
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) throw parseFailure(response.status, value);
  if (response.status === 202) {
    const operation = isRecord(value) && "data" in value ? value.data : value;
    if (isRecord(operation) && typeof operation.operationToken === "string") return operation as T;
  }
  if (!isRecord(value) || !("data" in value)) {
    throw new ApiError(response.status, "INTERNAL_ERROR", "Вътрешна грешка. Опитайте отново.", true);
  }
  return value.data as T;
}

export function reviewStory(storyId: string, observedDevelopmentIds: string[]): Promise<StoryDetail> {
  return sendStoryCommand(`/stories/${encodeURIComponent(storyId)}/review`, "POST", {
    observedDevelopmentIds,
  });
}

export function followStory(storyId: string): Promise<StoryDetail> {
  return sendStoryCommand(`/stories/${encodeURIComponent(storyId)}/follow`, "PUT");
}

export function unfollowStory(storyId: string): Promise<StoryDetail> {
  return sendStoryCommand(`/stories/${encodeURIComponent(storyId)}/follow`, "DELETE");
}

export function ignoreStory(storyId: string): Promise<StoryDetail> {
  return sendStoryCommand(`/stories/${encodeURIComponent(storyId)}/ignore`, "POST");
}

export function startArticle(storyId: string, idempotencyKey: string): Promise<ArticleDetail> {
  return sendStoryCommand(
    `/stories/${encodeURIComponent(storyId)}/articles`,
    "POST",
    undefined,
    { "Idempotency-Key": idempotencyKey },
  );
}

export function updateArticleContent(
  articleId: string,
  expectedVersion: number,
  title: string,
  body: string,
): Promise<ArticleDetail> {
  return sendStoryCommand(`/articles/${encodeURIComponent(articleId)}/content`, "PUT", {
    expectedVersion,
    title,
    body,
  });
}

export function updateArticleFocus(articleId: string, focus: string): Promise<ArticleDetail> {
  return sendStoryCommand(`/articles/${encodeURIComponent(articleId)}/focus`, "PUT", { focus });
}

/**
 * «Отбележи като готова». The client sends only the version it observed and the
 * confirmed canonical text; the server revalidates and decides. No warnings, no
 * digest and no override flag are ever sent from the editor.
 */
export function markArticleReady(articleId: string, expectedVersion: number): Promise<ArticleDetail> {
  return sendStoryCommand(`/articles/${encodeURIComponent(articleId)}/ready`, "POST", {
    expectedVersion,
  });
}

/**
 * `Редактирай` from `Готова`. An explicit decision, not a content edit: the
 * readiness checkpoint is invalidated server-side and no version is negotiated.
 */
export function reopenArticle(articleId: string): Promise<ArticleDetail> {
  return sendStoryCommand(`/articles/${encodeURIComponent(articleId)}/reopen`, "POST");
}

/**
 * `Финализирай` — the last editorial step, not publication. The client sends the
 * version it observed plus an idempotency key, and the server revalidates and
 * compares the fresh digest against the recorded readiness digest. The client
 * never sends a digest as authority.
 */
export function finalizeArticle(
  articleId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<FinalizeResult> {
  return sendStoryCommand(
    `/articles/${encodeURIComponent(articleId)}/finalize`,
    "POST",
    { expectedVersion },
    { "Idempotency-Key": idempotencyKey },
  );
}

export function updateArticleTitle(
  articleId: string,
  expectedVersion: number,
  title: string,
): Promise<ArticleDetail> {
  return sendStoryCommand(`/articles/${encodeURIComponent(articleId)}/title`, "PUT", {
    expectedVersion,
    title,
  });
}

export async function makeArticleDraft(articleId: string, idempotencyKey: string): Promise<ArticleDetail> {
  const value = await sendStoryCommand<unknown>(
    `/articles/${encodeURIComponent(articleId)}/draft`,
    "POST",
    undefined,
    { "Idempotency-Key": idempotencyKey },
  );
  if (isRecord(value) && typeof value.operationToken === "string") {
    // D2B: this polls for up to a minute of real provider time. The previous
    // ~2s budget ended while the backend operation was still correctly running,
    // and the editor was told the Draft was not ready. An exhausted budget is a
    // transport message about the wait, never a claim that generation failed.
    const article = await pollOperationFor<ArticleDetail>(value.operationToken, {
      budget: DRAFT_POLL_BUDGET,
      malformed: "Черновата не можа да бъде създадена. Опитайте отново.",
      succeededWithoutResult: "Операцията не върна създадената чернова.",
      exhausted: "Черновата все още се създава. Опитайте отново след малко.",
      extract: operationArticle,
    });
    // A successful draft operation always carries the Article, so the helper
    // throws before it could resolve `null` here.
    return article as ArticleDetail;
  }
  if (isRecord(value) && "content" in value) return value as unknown as ArticleDetail;
  throw new ApiError(200, "INTERNAL_ERROR", "Черновата не върна актуализирана статия.", true);
}

/**
 * «Днес → Чернова» (D2): one click, one intent, one backend orchestration.
 *
 * The browser never chains research → article → focus → draft. It expresses a
 * single editorial decision and the application layer owns the sequence, so the
 * partial-failure semantics cannot live in React.
 *
 * The bounded poll is deliberately much longer than Research's ~2s: this one
 * operation can legitimately include a live research round, page opening and a
 * real model generation. An exhausted budget is a statement about the *wait*
 * ("still preparing"), never a claim that generation failed, and the backend
 * work is never cancelled because the browser stopped looking.
 */
export const QUICK_DRAFT_POLL_BUDGET: OperationPollBudget = { attempts: 180, delayMs: 1000 };

function operationQuickDraft(value: ResearchOperation): QuickDraftResult | null {
  const candidate = value.result;
  if (!isRecord(candidate)) return null;
  const data = isRecord(candidate) && "data" in candidate && isRecord(candidate.data)
    ? candidate.data
    : candidate;
  if (typeof data.status !== "string") return null;
  if (data.status !== "draft_created" && data.status !== "existing_article" && data.status !== "needs_attention") {
    return null;
  }
  return data as unknown as QuickDraftResult;
}

/**
 * Ask the backend for one Quick Draft and wait for its bounded operation.
 *
 * `idempotencyKey` is required and generated once per click, so a double click,
 * a browser retry and a returning editor all address the same operation.
 */
export async function quickDraftStory(
  storyId: string,
  idempotencyKey: string,
): Promise<QuickDraftResult> {
  const value = await sendStoryCommand<unknown>(
    `/stories/${encodeURIComponent(storyId)}/quick-draft`,
    "POST",
    undefined,
    { "Idempotency-Key": idempotencyKey },
  );
  if (!isRecord(value) || typeof value.operationToken !== "string") {
    throw new ApiError(200, "INTERNAL_ERROR", "Черновата не върна резултат.", true);
  }
  const result = await pollOperationFor<QuickDraftResult>(value.operationToken, {
    budget: QUICK_DRAFT_POLL_BUDGET,
    malformed: "Черновата не можа да бъде подготвена. Опитайте отново.",
    succeededWithoutResult: "Операцията не върна резултат за черновата.",
    // Truthful wording about the wait. Never "generation failed": the backend
    // may still be working, and the editor's own retry reattaches to it.
    exhausted: "Черновата все още се подготвя. Опитайте отново след малко.",
    extract: operationQuickDraft,
  });
  return result as QuickDraftResult;
}

export interface ResearchOperation {
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "COMPLETED" | "FAILED" | "ERROR";
  operationToken?: string;
  result?: unknown;
  story?: unknown;
  error?: unknown;
}

/**
 * The one bounded-poll policy for `GET /api/v1/operations/{token}`.
 *
 * Every long-running editor action (Research, Refresh, Draft) answers `202` with
 * an operation token and settles later on that same endpoint, so they share this
 * loop instead of each carrying its own copy. The budget is still *bounded*: an
 * exhausted budget is a transport outcome ("still working, ask again shortly"),
 * never a claim that the work failed.
 */
export interface OperationPollBudget {
  attempts: number;
  delayMs: number;
}

/**
 * A real external model provider takes far longer than a couple of seconds.
 * D2B replaced Draft's previous 8 x 250ms (~2s) budget with this one, because a
 * still-correctly-running operation must never be reported to the editor as a
 * failure. It matches the budget «Обнови» already used for a real collection
 * round, so all long operations now share one policy.
 */
export const DRAFT_POLL_BUDGET: OperationPollBudget = { attempts: 60, delayMs: 1000 };

// A Story research round keeps its existing budget. Only Draft's budget changed,
// and every operation here is still bounded.
const RESEARCH_POLL_BUDGET: OperationPollBudget = { attempts: 8, delayMs: 250 };

interface OperationPollOptions<T> {
  budget: OperationPollBudget;
  /** Said when the server answered something that is not an operation at all. */
  malformed: string;
  /** Said when the bounded client budget ran out. Must not imply failure. */
  exhausted: string;
  /**
   * Said when the operation reported success but carried no payload. Omitted for
   * operations with no payload to unwrap, whose success *is* the result: the
   * helper then resolves with `null` instead of throwing.
   */
  succeededWithoutResult?: string;
  /** The payload the editor is waiting for, or `null` while still running. */
  extract: (value: ResearchOperation) => T | null;
}

/**
 * Poll one operation to a terminal state.
 *
 * Resolves with the extracted payload, or `null` for a successful operation that
 * had no payload to unwrap. Throws an :class:`ApiError` for a malformed answer, a
 * real backend failure, a success with a missing payload, or an exhausted client
 * budget.
 */
async function pollOperationFor<T>(
  operationToken: string,
  options: OperationPollOptions<T>,
): Promise<T | null> {
  const { budget } = options;
  for (let attempt = 0; attempt < budget.attempts; attempt += 1) {
    if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, budget.delayMs));
    const value = await getData<unknown>(`/operations/${encodeURIComponent(operationToken)}`);
    if (!isResearchOperation(value)) {
      throw new ApiError(0, "INTERNAL_ERROR", options.malformed, true);
    }
    // A payload is authoritative whenever it is present, exactly as before.
    const payload = options.extract(value);
    if (payload !== null) return payload;
    const status = value.status.toUpperCase();
    if (status === "FAILED" || status === "ERROR") throw operationFailure(value);
    if (status === "SUCCEEDED" || status === "COMPLETED") {
      if (options.succeededWithoutResult === undefined) return null;
      throw new ApiError(0, "INTERNAL_ERROR", options.succeededWithoutResult, true);
    }
  }
  throw new ApiError(0, "INTERNAL_ERROR", options.exhausted, true);
}

function isResearchOperation(value: unknown): value is ResearchOperation {
  return isRecord(value) && typeof value.status === "string";
}

function operationStory(value: ResearchOperation): StoryDetail | null {
  const candidate = value.story ?? value.result;
  if (!isRecord(candidate)) return null;
  const data = "data" in candidate && isRecord(candidate.data) ? candidate.data : candidate;
  return typeof data.id === "string" && "missingInformation" in data ? data as unknown as StoryDetail : null;
}

function operationArticle(value: ResearchOperation): ArticleDetail | null {
  const candidate = value.result;
  if (!isRecord(candidate)) return null;
  const data = "data" in candidate && isRecord(candidate.data) ? candidate.data : candidate;
  return typeof data.id === "string" && "content" in data ? data as unknown as ArticleDetail : null;
}

function operationFailure(value: ResearchOperation): ApiError {
  const raw = isRecord(value.error) ? value.error : undefined;
  return new ApiError(
    0,
    raw && typeof raw.code === "string" && apiErrorCodes.has(raw.code) ? raw.code as ApiErrorCode : "INTERNAL_ERROR",
    raw && typeof raw.message === "string" ? raw.message : "Проучването не можа да се изпълни. Опитайте отново.",
    raw && typeof raw.retryable === "boolean" ? raw.retryable : true,
  );
}

async function pollResearchOperation(operationToken: string): Promise<StoryDetail> {
  const story = await pollOperationFor<StoryDetail>(operationToken, {
    budget: RESEARCH_POLL_BUDGET,
    malformed: "Проучването не можа да се изпълни. Опитайте отново.",
    succeededWithoutResult: "Проучването не върна актуализирана история.",
    exhausted: "Проучването все още не е готово. Опитайте отново.",
    extract: operationStory,
  });
  // A successful research operation always carries its Story, so the helper
  // throws before it could resolve `null` here.
  return story as StoryDetail;
}

export async function researchMoreStory(storyId: string): Promise<StoryDetail> {
  const value = await sendStoryCommand<unknown>(
    `/stories/${encodeURIComponent(storyId)}/research`,
    "POST",
    undefined,
    { "Idempotency-Key": createIdempotencyKey() },
  );
  if (isRecord(value) && typeof value.operationToken === "string") return pollResearchOperation(value.operationToken);
  if (isRecord(value) && "missingInformation" in value) return value as unknown as StoryDetail;
  throw new ApiError(200, "INTERNAL_ERROR", "Проучването не върна актуализирана история.", true);
}

export const researchStory = researchMoreStory;

// A newsroom refresh performs real network collection, so its bounded poll is
// longer than a Story research round. It is still bounded: the editor is never
// left waiting on a job monitor, and a stalled run ends in a calm retry. This
// is also the budget Draft now shares, which is why both are one minute.
const REFRESH_POLL_BUDGET: OperationPollBudget = { attempts: 60, delayMs: 1000 };

async function pollOperation(operationToken: string): Promise<void> {
  // A refresh has no payload to unwrap: a successful operation *is* the result.
  await pollOperationFor<never>(operationToken, {
    budget: REFRESH_POLL_BUDGET,
    malformed: "Новините не можаха да се обновят. Опитайте отново.",
    exhausted: "Обновяването още не е приключило. Опитайте отново.",
    extract: () => null,
  });
}

/** The one editor-facing newsroom action. Canonical Today is refetched after it. */
export async function refreshNewsroom(): Promise<void> {
  const value = await sendStoryCommand<unknown>(
    "/today/refresh",
    "POST",
    undefined,
    { "Idempotency-Key": createIdempotencyKey() },
  );
  if (isRecord(value) && typeof value.operationToken === "string") {
    await pollOperation(value.operationToken);
    return;
  }
  throw new ApiError(200, "INTERNAL_ERROR", "Обновяването не върна резултат.", true);
}


async function getData<T>(path: string, params?: URLSearchParams): Promise<T> {
  const query = params?.toString();
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}${query ? `?${query}` : ""}`, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Връзката с редакционната система е прекъсната.", true);
  }
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) throw parseFailure(response.status, value);
  if (!isRecord(value) || !("data" in value)) {
    throw new ApiError(response.status, "INTERNAL_ERROR", "Вътрешна грешка. Опитайте отново.", true);
  }
  return value.data as T;
}

export function getToday(): Promise<TodayProjection> {
  return getData("/today");
}

export function getStories(filter: StoryFilter = "all", query = ""): Promise<{ stories: import("./dto").StorySummary[] }> {
  return getData("/stories", new URLSearchParams({ filter, query }));
}

export function getStory(id: string): Promise<StoryDetail> {
  return getData(`/stories/${encodeURIComponent(id)}`);
}

export function getArticles(
  filter: ArticleFilter = "all",
  query = "",
): Promise<{ articles: ArticleSummary[] }> {
  return getData("/articles", new URLSearchParams({ filter, query }));
}

export function getArticle(id: string): Promise<ArticleDetail> {
  return getData(`/articles/${encodeURIComponent(id)}`);
}

export function getArchive(query = ""): Promise<{ articles: ArchiveArticle[] }> {
  return getData("/archive", new URLSearchParams({ query }));
}

export function getFinalizedArticle(id: string): Promise<ArchiveArticle> {
  return getData(`/archive/${encodeURIComponent(id)}`);
}

export type ArticleFilter = "all" | "preparation" | "draft" | "ready";
export type StoryFilter = "all" | "followed" | "developments" | "ignored";
