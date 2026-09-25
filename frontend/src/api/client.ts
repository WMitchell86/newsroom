import type {
  ApiErrorCode,
  ArchiveArticle,
  ArticleDetail,
  ArticleSummary,
  StoryDetail,
  TodayProjection,
} from "./dto";

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
    for (let attempt = 0; attempt < DRAFT_POLL_ATTEMPTS; attempt += 1) {
      if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, DRAFT_POLL_DELAY_MS));
      const operation = await getData<unknown>(`/operations/${encodeURIComponent(value.operationToken)}`);
      if (!isResearchOperation(operation)) {
        throw new ApiError(0, "INTERNAL_ERROR", "Черновата не можа да бъде създадена. Опитайте отново.", true);
      }
      const article = operationArticle(operation);
      if (article) return article;
      const status = operation.status.toUpperCase();
      if (status === "FAILED" || status === "ERROR") throw operationFailure(operation);
      if (status === "SUCCEEDED" || status === "COMPLETED") {
        throw new ApiError(0, "INTERNAL_ERROR", "Операцията не върна създадената чернова.", true);
      }
    }
    throw new ApiError(0, "INTERNAL_ERROR", "Черновата още не е готова. Опитайте отново.", true);
  }
  if (isRecord(value) && "content" in value) return value as unknown as ArticleDetail;
  throw new ApiError(200, "INTERNAL_ERROR", "Черновата не върна актуализирана статия.", true);
}

export interface ResearchOperation {
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "COMPLETED" | "FAILED" | "ERROR";
  operationToken?: string;
  result?: unknown;
  story?: unknown;
  error?: unknown;
}

const RESEARCH_POLL_ATTEMPTS = 8;
const RESEARCH_POLL_DELAY_MS = 250;
const DRAFT_POLL_ATTEMPTS = 8;
const DRAFT_POLL_DELAY_MS = 250;

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
  for (let attempt = 0; attempt < RESEARCH_POLL_ATTEMPTS; attempt += 1) {
    if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, RESEARCH_POLL_DELAY_MS));
    const value = await getData<unknown>(`/operations/${encodeURIComponent(operationToken)}`);
    if (!isResearchOperation(value)) throw new ApiError(0, "INTERNAL_ERROR", "Проучването не можа да се изпълни. Опитайте отново.", true);
    const story = operationStory(value);
    if (story) return story;
    const status = value.status.toUpperCase();
    if (status === "FAILED" || status === "ERROR") throw operationFailure(value);
    if (status === "SUCCEEDED" || status === "COMPLETED") {
      throw new ApiError(0, "INTERNAL_ERROR", "Проучването не върна актуализирана история.", true);
    }
  }
  throw new ApiError(0, "INTERNAL_ERROR", "Проучването все още не е готово. Опитайте отново.", true);
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
// left waiting on a job monitor, and a stalled run ends in a calm retry.
const REFRESH_POLL_ATTEMPTS = 60;
const REFRESH_POLL_DELAY_MS = 1000;

async function pollOperation(operationToken: string): Promise<void> {
  for (let attempt = 0; attempt < REFRESH_POLL_ATTEMPTS; attempt += 1) {
    if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, REFRESH_POLL_DELAY_MS));
    const value = await getData<unknown>(`/operations/${encodeURIComponent(operationToken)}`);
    if (!isResearchOperation(value)) {
      throw new ApiError(0, "INTERNAL_ERROR", "Новините не можаха да се обновят. Опитайте отново.", true);
    }
    const status = value.status.toUpperCase();
    if (status === "FAILED" || status === "ERROR") throw operationFailure(value);
    if (status === "SUCCEEDED" || status === "COMPLETED") return;
  }
  throw new ApiError(0, "INTERNAL_ERROR", "Обновяването още не е приключило. Опитайте отново.", true);
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
