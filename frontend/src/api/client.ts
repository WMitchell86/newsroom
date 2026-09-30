import type {
  ApiErrorCode,
  ArchiveArticle,
  ArticleDetail,
  ArticleSummary,
  NewSourceInput,
  QuickDraftResult,
  SourceChanges,
  SourceRow,
  SourcesProjection,
  StoryDetail,
  TodayProjection,
  TodayScope,
  OperationSummary,
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

/**
 * V1.2-G4.5 — a code this build has never heard of is NOT an internal error.
 *
 * This used to be a closed set, and the closed set was wrong twice over. It
 * listed ten codes while `ApiErrorCode` declares twenty-one, so eleven codes the
 * product had deliberately introduced — every G4.1/G4.3 readiness reason such as
 * `NO_DRAFT_MATERIAL`, `FOCUS_NOT_CONFIRMED` and `STORY_UNAVAILABLE` — were
 * silently discarded on the way in. A refusal whose whole point is that it names
 * its own reason reached the editor as "Вътрешна грешка. Опитайте отново."
 *
 * And the set had no safety value to lose: the envelope is already validated
 * structurally, and a code is a label, not a shape. So the gate is gone and the
 * code travels through as the server sent it. A malformed envelope still
 * becomes an internal error, which is the only thing that statement is true of.
 */
function parseFailure(status: number, value: unknown): ApiError {
  if (isRecord(value) && isRecord(value.error)) {
    const candidate = value.error;
    if (
      typeof candidate.code === "string" &&
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

/**
 * «Започни от идея» (V1.2-G4.20) — the editor's own hint.
 *
 * The hint is a SEARCH QUERY. The server searches, opens the pages it finds
 * and returns them as ordinary Stories with their own real URLs; the hint
 * itself is never evidence and never becomes a source. The reply therefore
 * carries what actually happened — including the pages that could NOT be
 * opened, each with its real failure category — so the UI can say "0 found"
 * or "1 of 3 would not open" rather than a generic failure.
 */
export interface HintSeedResult {
  hint: string;
  /**
   * `storyId` is what the editor is navigated to. `itemId` is the raw inbox
   * row and is NOT a route id — `/stories/:id` answers "Невалиден Story." for
   * it. Sending the item id produced a dead link on the very first click.
   */
  opened: { title: string; url: string; itemId: string; storyId: string }[];
  openedCount: number;
  considered: number;
  /** Opened fine, but the newsroom blocks that publisher. */
  blocked: { url: string; title: string }[];
  unopened: { url: string; status: string; detail: string }[];
  providerChain: string[];
  searchStatus: string;
}

export function seedStoriesFromHint(hint: string): Promise<HintSeedResult> {
  return sendStoryCommand<HintSeedResult>("/stories/hint", "POST", { hint });
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
 * `Стил` — the optional Voice choice (V1.2-G4.3 §D).
 *
 * An empty string is `Автоматично`. It never creates an Article, never rewrites
 * the current Draft, and never withdraws readiness: it applies to the NEXT
 * Draft or Rewrite.
 */
export function updateArticleVoice(articleId: string, voice: string): Promise<ArticleDetail> {
  return sendStoryCommand(`/articles/${encodeURIComponent(articleId)}/voice`, "PUT", { voice });
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
 * `Пренапиши` — a new version of THIS Article from the editor's own comment
 * (V1.2-G4.3 §E).
 *
 * The comment is the entire request. There is no facts payload, no evidence
 * override and no state transition: the backend reuses the current factual
 * basis and returns a new content version of the same Article.
 *
 * The comment is sent ONLY on an explicit click, and the component keeps it in
 * local state until the operation succeeds, so a failure leaves the editor's
 * words on screen for the retry (§E4).
 */
/** V1.2-G4.18 — the editor's controls over a rewrite, beside their words. */
export const REWRITE_LENGTHS = [
  { value: "", label: "Както е" },
  { value: "short", label: "Кратка" },
  { value: "standard", label: "Стандартна" },
  { value: "full", label: "Пълна статия" },
] as const;

export const REWRITE_MODES = [
  { value: "", label: "Автоматично" },
  { value: "MODE_STANDARD_NEWS", label: "Новина" },
  { value: "MODE_EVENT_PREVIEW", label: "Събитие" },
  { value: "MODE_CULTURE_FEATURE", label: "Култура" },
  { value: "MODE_BRIEF", label: "Кратка новина" },
] as const;

export async function rewriteArticle(
  articleId: string,
  comment: string,
  idempotencyKey: string,
  controls: { mode?: string; length?: string } = {},
): Promise<ArticleDetail> {
  const value = await sendStoryCommand<unknown>(
    `/articles/${encodeURIComponent(articleId)}/rewrite`,
    "POST",
    // Only the keys the editor actually chose travel. Sending empty values
    // would be a claim that they were set.
    {
      comment,
      ...(controls.mode ? { mode: controls.mode } : {}),
      ...(controls.length ? { length: controls.length } : {}),
    },
    { "Idempotency-Key": idempotencyKey },
  );
  if (isRecord(value) && typeof value.operationToken === "string") {
    // The same long-operation policy as a first Draft: a rewrite is a real
    // generation, and an exhausted budget is a statement about the wait, never a
    // claim that the rewrite failed.
    const article = await pollOperationFor<ArticleDetail>(value.operationToken, {
      budget: DRAFT_POLL_BUDGET,
      malformed: "Пренаписването не можа да се извърши. Опитайте отново.",
      succeededWithoutResult: "Операцията не върна пренаписан текст.",
      exhausted: "Пренаписването все още тече. Опитайте отново след малко.",
      extract: operationArticle,
    });
    return article as ArticleDetail;
  }
  if (isRecord(value) && "content" in value) return value as unknown as ArticleDetail;
  throw new ApiError(
    200,
    "INTERNAL_ERROR",
    "Пренаписването не върна актуализирана статия.",
    true,
  );
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
/**
 * V1.2-G2.2 §1: the ONE long-operation policy.
 *
 * Story Research used to keep its own ~2s budget (8 x 250ms) from before the D2B
 * work, while Quick Draft waited 180s. A real research round performs a web
 * search and opens pages, so it routinely outran 2 seconds: the backend was
 * still correctly working while the UI told the editor the research had failed
 * and asked for a manual retry. Research now follows the SAME long policy as
 * every other long operation, and there is no second operation registry and no
 * second polling loop.
 */
export const LONG_OPERATION_POLL_BUDGET: OperationPollBudget = { attempts: 180, delayMs: 1000 };

export const QUICK_DRAFT_POLL_BUDGET: OperationPollBudget = LONG_OPERATION_POLL_BUDGET;

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

interface OperationPollCommon<T> {
  budget: OperationPollBudget;
  /** Said when the server answered something that is not an operation at all. */
  malformed: string;
  /**
   * Said when the operation reported success but carried no payload. Omitted for
   * operations with no payload to unwrap, whose success *is* the result: the
   * helper then resolves with `null` instead of throwing.
   */
  succeededWithoutResult?: string;
  /**
   * A single unreachable poll is a transport hiccup, not a failed operation.
   * Off by default; Research turns it on because its rounds are long, so one
   * dropped poll among 180 must not abort a round that is still working.
   */
  tolerateUnreachablePolls?: boolean;
  /** The payload the editor is waiting for, or `null` while still running. */
  extract: (value: ResearchOperation) => T | null;
}

/**
 * An exhausted budget ends ONE of two ways, and a caller must choose one.
 *
 * `exhausted` is the historical behaviour: throw one calm sentence that must
 * not imply failure. `onExhausted` is V1.2-G2.2 §2, for Research: a long round
 * that is still running when the client stops looking is NOT a failure, so the
 * caller receives the token and reattaches to the same operation.
 */
type OperationPollOptions<T> = OperationPollCommon<T> &
  (
    | { exhausted: string; onExhausted?: never }
    | { exhausted?: never; onExhausted: (operationToken: string) => T }
  );

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
    let value: unknown;
    try {
      value = await getData<unknown>(`/operations/${encodeURIComponent(operationToken)}`);
    } catch (error) {
      const unreachable =
        options.tolerateUnreachablePolls === true &&
        error instanceof ApiError &&
        error.code === "NETWORK_ERROR";
      if (unreachable) continue;
      throw error;
    }
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
  if (options.onExhausted) return options.onExhausted(operationToken);
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
    // The server's own code, for the same reason as `parseFailure`: a code this
    // build has not seen is a reason the editor has not been shown yet, not an
    // internal error. Only a missing or non-string code falls back.
    raw && typeof raw.code === "string" ? (raw.code as ApiErrorCode) : "INTERNAL_ERROR",
    raw && typeof raw.message === "string" ? raw.message : "Проучването не можа да се изпълни. Опитайте отново.",
    raw && typeof raw.retryable === "boolean" ? raw.retryable : true,
  );
}

/**
 * V1.2-G2.2 §1/§2 — the outcome of `Проучи още`, as the editor experiences it.
 *
 * `completed` means the backend finished and the Story is the fresh canonical
 * projection. `continuing` means the bounded client wait ended while the real
 * operation was still running: a transport timeout is NOT a research failure,
 * so it is never reported as one. The token travels with it so the editor can
 * reattach to the same operation with `Провери статуса` instead of starting a
 * second one.
 */
export type ResearchOutcome =
  | { status: "completed"; story: StoryDetail }
  | { status: "continuing"; operationToken: string };

const RESEARCH_POLL_MESSAGES = {
  malformed: "Проучването не можа да се изпълни. Опитайте отново.",
  succeededWithoutResult: "Проучването не върна актуализирана история.",
} as const;

/**
 * Follow one research operation on the SHARED long-operation helper.
 *
 * §1: there is one polling loop for every long operation, and research uses it
 * exactly as Draft and «Обнови» do. The only differences are the two options
 * research needs: an exhausted budget resolves with the token instead of
 * throwing, and a single unreachable poll is tolerated because a research round
 * is long and the backend is still working.
 */
async function followResearchOperation(operationToken: string): Promise<ResearchOutcome> {
  const outcome = await pollOperationFor<ResearchOutcome>(operationToken, {
    budget: LONG_OPERATION_POLL_BUDGET,
    malformed: RESEARCH_POLL_MESSAGES.malformed,
    succeededWithoutResult: RESEARCH_POLL_MESSAGES.succeededWithoutResult,
    extract: (value) => {
      const story = operationStory(value);
      return story ? { status: "completed", story } : null;
    },
    onExhausted: (token) => ({ status: "continuing", operationToken: token }),
    tolerateUnreachablePolls: true,
  });
  // `succeededWithoutResult` is supplied above, so the helper throws rather than
  // resolving `null`. Stated explicitly so the invariant survives a refactor of
  // either side instead of leaking a `null` outcome to the UI.
  if (outcome === null) {
    throw new ApiError(0, "INTERNAL_ERROR", RESEARCH_POLL_MESSAGES.succeededWithoutResult, true);
  }
  return outcome;
}

/** `Провери статуса`: reattach to the running operation, never start another. */
export function checkResearchStatus(operationToken: string): Promise<ResearchOutcome> {
  return followResearchOperation(operationToken);
}

export async function researchMoreStory(storyId: string): Promise<ResearchOutcome> {
  const value = await sendStoryCommand<unknown>(
    `/stories/${encodeURIComponent(storyId)}/research`,
    "POST",
    undefined,
    { "Idempotency-Key": createIdempotencyKey() },
  );
  if (isRecord(value) && typeof value.operationToken === "string") {
    return followResearchOperation(value.operationToken);
  }
  if (isRecord(value) && "missingInformation" in value) {
    return { status: "completed", story: value as unknown as StoryDetail };
  }
  throw new ApiError(200, "INTERNAL_ERROR", RESEARCH_POLL_MESSAGES.succeededWithoutResult, true);
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

/**
 * V1.2-G4.1 §A4 — `region` is the default Burgas working desk. The scope is an
 * explicit, allow-listed query parameter: the backend decides what the desk
 * means, and the client never filters rows itself.
 */
export function getToday(scope: TodayScope = "region"): Promise<TodayProjection> {
  return getData("/today", new URLSearchParams({ scope }));
}

/**
 * V1.2-G4.5: per-role routing health. A pure read — the routing plan the
 * backend would follow, no provider call, no spend — so the header can say
 * whether the system can actually work right now.
 */
export function getRoleHealth(): Promise<{
  ok: boolean;
  roles: import("./dto").RoleHealth[];
  unroutableRoles: string[];
  remedy: string;
}> {
  return getData("/health");
}

export function getStories(
  filter: StoryFilter = "all",
  query = "",
  page = 1,
  perPage?: number,
): Promise<{
  stories: import("./dto").StorySummary[];
  /** V1.2-G4.7 — filter counts, so the nav does not imply a split it lacks. */
  counts?: Partial<Record<StoryFilter, number>>;
  /** V1.2-G4.14 — rows matching the filter, before paging. */
  total?: number;
  page?: number;
  perPage?: number;
}> {
  const params = new URLSearchParams({ filter, query });
  if (page > 1) params.set("page", String(page));
  if (perPage) params.set("per_page", String(perPage));
  return getData("/stories", params);
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

/**
 * V1.2-G4.6: the editor's own requests, newest first.
 *
 * Bounded and truthful: this is the history the server kept, so a task that
 * was interrupted by a restart shows as failed with its reason rather than
 * disappearing. An empty list means the server has no history, not that
 * nothing was ever asked for.
 */
export function getOperations(): Promise<{ operations: OperationSummary[] }> {
  return getData("/operations");
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

// ---------- V1.2-G4: Settings / Sources ----------

/**
 * The registry, as the editor sees it.
 *
 * A plain same-origin GET. There is no frontend-owned source list anywhere in
 * the SPA: this projection is the only thing the Sources screen renders, and it
 * is produced by the same canonical registry the collector reads (§2).
 */
export function getSources(): Promise<SourcesProjection> {
  return getData("/settings/sources");
}

/** `+ Добави източник` (§9). Every field is sent explicitly. */
export function createSource(input: NewSourceInput): Promise<SourceRow> {
  return sendStoryCommand<SourceRow>("/settings/sources", "POST", input);
}

/**
 * `Редактирай` and both toggles (§10).
 *
 * Only the changed fields are sent. The backend's key set is closed, so a future
 * caller cannot widen what this screen is able to reach — the client is not the
 * thing keeping `source_id` immutable, the API is.
 */
export function updateSource(id: string, changes: SourceChanges): Promise<SourceRow> {
  return sendStoryCommand<SourceRow>(
    `/settings/sources/${encodeURIComponent(id)}`,
    "PUT",
    changes,
  );
}

export type ArticleFilter = "all" | "preparation" | "draft" | "ready";
export type StoryFilter = "all" | "followed" | "developments" | "ignored";
