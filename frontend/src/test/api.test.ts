import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ArticleDetail } from "../api/dto";
import { ApiError, DRAFT_POLL_BUDGET, followStory, getArticles, getToday, ignoreStory, makeArticleDraft, markArticleReady, refreshNewsroom, researchMoreStory, reviewStory, startArticle, unfollowStory, updateArticleFocus, updateArticleTitle } from "../api/client";
const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("read-only API client", () => {
  it("uses a same-origin GET and unwraps the data envelope", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: { newDevelopments: [], newStories: [], articlesRequiringAction: [], problems: [] } }),
    } as Response);

    await expect(getToday()).resolves.toEqual({ newDevelopments: [], newStories: [], articlesRequiringAction: [], problems: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/today",
      expect.objectContaining({
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      }),
    );
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("method");
  });

  it("encodes Article filter and query as same-origin GET parameters", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: { articles: [] } }),
    } as Response);

    await expect(getArticles("draft", "булевард & ремонт")).resolves.toEqual({ articles: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/articles?filter=draft&query=%D0%B1%D1%83%D0%BB%D0%B5%D0%B2%D0%B0%D1%80%D0%B4+%26+%D1%80%D0%B5%D0%BC%D0%BE%D0%BD%D1%82",
      {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      },
    );
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("method");
  });
  it("preserves the structured error envelope as ApiError", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: {
          code: "VALIDATION_ERROR",
          message: "Проверете подадените данни.",
          retryable: false,
          fieldErrors: [{ field: "filter" }],
        },
      }),
    } as Response);

    await expect(getToday()).rejects.toEqual(expect.objectContaining<ApiError>({
      name: "ApiError",
      status: 409,
      code: "VALIDATION_ERROR",
      message: "Проверете подадените данни.",
      retryable: false,
    }));
  });

  it("maps the four Story commands to the existing B1 endpoints", async () => {
    const detail = { id: "s-one" };
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: detail }),
    } as Response);

    await reviewStory("s-one", ["dev_a", "dev_b"]);
    await followStory("s-one");
    await unfollowStory("s-one");
    await ignoreStory("s-one");

    expect(fetchMock.mock.calls.map(([path, init]) => [path, init.method, init.body])).toEqual([
      ["/api/v1/stories/s-one/review", "POST", JSON.stringify({ observedDevelopmentIds: ["dev_a", "dev_b"] })],
      ["/api/v1/stories/s-one/follow", "PUT", undefined],
      ["/api/v1/stories/s-one/follow", "DELETE", undefined],
      ["/api/v1/stories/s-one/ignore", "POST", undefined],
    ]);
    expect(fetchMock.mock.calls.every(([, init]) => !(init.headers as Record<string, string> | undefined)?.["Idempotency-Key"])).toBe(true);
  });

  it("uses the exact C1 Article command endpoints and request bodies", async () => {
    const article = { id: "art-one" };
    fetchMock.mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ data: article }),
    } as Response);

    await startArticle("s one", "start-key");
    await updateArticleFocus("art one", "Ясен фокус");
    await updateArticleTitle("art one", 2, "Работно заглавие");

    expect(fetchMock.mock.calls.map(([path, init]) => [path, init.method, init.body, (init.headers as Record<string, string>)["Idempotency-Key"]])).toEqual([
      ["/api/v1/stories/s%20one/articles", "POST", undefined, "start-key"],
      ["/api/v1/articles/art%20one/focus", "PUT", JSON.stringify({ focus: "Ясен фокус" }), undefined],
      ["/api/v1/articles/art%20one/title", "PUT", JSON.stringify({ expectedVersion: 2, title: "Работно заглавие" }), undefined],
    ]);
  });

  it("posts the exact C4 readiness command with only the observed version", async () => {
    const article = { id: "art-one", state: "ready" };
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: article }) } as Response);

    await expect(markArticleReady("art one", 12)).resolves.toEqual(article);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/articles/art%20one/ready",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ expectedVersion: 12 }),
        credentials: "same-origin",
      }),
    );
    // The editor never sends warnings, a digest or an override flag.
    expect(JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      expectedVersion: 12,
    });
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).headers).not.toHaveProperty("Idempotency-Key", "");
  });

  it("surfaces a blocking readiness refusal with the stable editor code", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: {
          code: "SAFETY_BLOCKED",
          message: "Проверката на текущия текст откри пречи. Разгледайте предупрежденията.",
          retryable: false,
          fieldErrors: [],
        },
      }),
    } as Response);

    await expect(markArticleReady("art-one", 3)).rejects.toEqual(expect.objectContaining({
      status: 409,
      code: "SAFETY_BLOCKED",
      retryable: false,
    }));
  });

  it("uses the exact RESEARCH_MORE endpoint and supports synchronous 200", async () => {
    const detail = { id: "s-one", missingInformation: { items: [] } };
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: detail }) } as Response);

    await expect(researchMoreStory("s-one")).resolves.toEqual(detail);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/stories/s-one/research",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
      }),
    );
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).headers).not.toHaveProperty("Idempotency-Key", "");
  });

  it("polls a 202 transport operation and returns its refreshed Story", async () => {
    const detail = { id: "s-one", missingInformation: { items: [] } };
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ data: { operationToken: "op-1" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "running" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "succeeded", result: detail } }) } as Response);

    await expect(researchMoreStory("s-one")).resolves.toEqual(detail);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/operations/op-1");
  });

  it("surfaces an async research failure without changing the existing response", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ data: { operationToken: "op-fail" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "failed", error: { code: "SOURCE_UNAVAILABLE", message: "Източникът временно не е наличен.", retryable: true } } }) } as Response);

    await expect(researchMoreStory("s-one")).rejects.toEqual(expect.objectContaining({ code: "SOURCE_UNAVAILABLE", message: "Източникът временно не е наличен." }));
  });

  it("posts the exact Article draft endpoint with a required idempotency key", async () => {
    const article = { id: "art-one", content: { title: "Чернова", body: "Текст", version: 1 } };
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: article }) } as Response);

    await expect(makeArticleDraft("art one", "draft-key")).resolves.toEqual(article);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/articles/art%20one/draft",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": "draft-key" }),
      }),
    );
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("body");
  });

  it("polls a 202 Article draft operation until it returns the canonical Article", async () => {
    const article = { id: "art-one", content: { title: "Чернова", body: "Текст", version: 1 } };
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ data: { operationToken: "op-draft" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "running" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "succeeded", result: article } }) } as Response);

    await expect(makeArticleDraft("art-one", "draft-key")).resolves.toEqual(article);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/operations/op-draft");
  });

  it("surfaces a failed Article draft operation as a retryable ApiError", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ data: { operationToken: "op-draft-fail" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "failed", error: { code: "SOURCE_UNAVAILABLE", message: "Източникът временно не е наличен.", retryable: true } } }) } as Response);

    await expect(makeArticleDraft("art-one", "draft-key")).rejects.toEqual(expect.objectContaining({ code: "SOURCE_UNAVAILABLE", retryable: true }));
  });


  it("preserves the stable error envelope for Story mutations", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: {
          code: "INVALID_TRANSITION",
          message: "Това действие не е налично в текущото състояние.",
          retryable: false,
          fieldErrors: [],
        },
      }),
    } as Response);

    await expect(ignoreStory("s-one")).rejects.toEqual(expect.objectContaining({
      status: 409,
      code: "INVALID_TRANSITION",
      message: "Това действие не е налично в текущото състояние.",
      retryable: false,
    }));
  });
});

describe("the one newsroom refresh action", () => {
  it("posts the single refresh endpoint with an Idempotency-Key", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ data: { operationToken: "op-refresh" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "succeeded" } }) } as Response);

    await expect(refreshNewsroom()).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/today/refresh",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
      }),
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/operations/op-refresh");
  });

  it("polls a still-running refresh instead of reporting a false success", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ data: { operationToken: "op-busy" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "running" } }) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: { status: "succeeded", result: { new: 3 } } }) } as Response);

    await expect(refreshNewsroom()).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("surfaces a refresh failure with the sanitized editor message", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ data: { operationToken: "op-fail" } }) } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ data: { status: "failed", error: { code: "SOURCE_UNAVAILABLE", message: "Новините не можаха да се обновят.", retryable: true } } }),
      } as Response);

    await expect(refreshNewsroom()).rejects.toEqual(
      expect.objectContaining({ code: "SOURCE_UNAVAILABLE", message: "Новините не можаха да се обновят." }),
    );
  });

  it("rejects an overlapping refresh instead of starting a second collection", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: {
          code: "INVALID_TRANSITION",
          message: "няма активни източници за обновяване",
          retryable: false,
          fieldErrors: [],
        },
      }),
    } as Response);

    await expect(refreshNewsroom()).rejects.toEqual(
      expect.objectContaining({ status: 409, code: "INVALID_TRANSITION" }),
    );
  });
});

/**
 * D2B: the Draft polling budget.
 *
 * D2A found that Draft generation polled for only ~2 seconds (8 x 250ms). A real
 * external model provider routinely takes longer, so the client gave up while the
 * backend operation was still correctly running, and the editor was told
 * «Черновата още не е готова». These tests pin the hardened behavior.
 */
describe("the Draft operation polling budget", () => {
  const article = { id: "art-one", content: { title: "Чернова", body: "Текст", version: 1 } };

  function accepted(token = "op-draft"): Response {
    return { ok: true, status: 202, json: async () => ({ data: { operationToken: token } }) } as Response;
  }

  function operation(payload: unknown): Response {
    return { ok: true, status: 200, json: async () => ({ data: payload }) } as Response;
  }

  function pollsOf(token: string): unknown[][] {
    return fetchMock.mock.calls.filter((call) => String(call[0]).startsWith(`/api/v1/operations/${token}`));
  }

  /**
   * Start a Draft request and capture its outcome immediately, so a rejection
   * that happens while the fake clock is being flushed is never unhandled.
   */
  function startDraft(key: string): { settled: Promise<{ ok: true; value: ArticleDetail } | { ok: false; error: ApiError }> } {
    const outcome = makeArticleDraft("art-one", key).then(
      (value) => ({ ok: true as const, value }),
      (error: unknown) => ({ ok: false as const, error: error as ApiError }),
    );
    return { settled: outcome };
  }

  beforeEach(() => {
    // The budget is expressed in wall-clock time, so the tests drive the clock
    // instead of really waiting a minute for a real provider.
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("is a bounded budget in the general range used by other long operations", () => {
    expect(DRAFT_POLL_BUDGET.delayMs).toBeGreaterThan(0);
    const totalMs = DRAFT_POLL_BUDGET.attempts * DRAFT_POLL_BUDGET.delayMs;
    // Long enough for a real provider: the old budget was ~2000ms.
    expect(totalMs).toBeGreaterThanOrEqual(30_000);
    // Still bounded: no infinite wait, no job monitor.
    expect(totalMs).toBeLessThanOrEqual(10 * 60_000);
  });

  it("still succeeds when the operation takes far longer than the old two seconds", async () => {
    // 30 polls x 1000ms = 30s of real provider time, well past the old ~2s.
    fetchMock.mockResolvedValueOnce(accepted());
    for (let poll = 0; poll < 30; poll += 1) {
      fetchMock.mockResolvedValueOnce(operation({ status: "running" }));
    }
    fetchMock.mockResolvedValueOnce(operation({ status: "succeeded", result: article }));

    const { settled } = startDraft("draft-key");
    await vi.runAllTimersAsync();

    expect(await settled).toEqual({ ok: true, value: article });
    expect(pollsOf("op-draft")).toHaveLength(31);
  });

  it("follows pending -> running -> succeeded and returns the canonical Article", async () => {
    fetchMock.mockResolvedValueOnce(accepted());
    fetchMock.mockResolvedValueOnce(operation({ status: "pending" }));
    fetchMock.mockResolvedValueOnce(operation({ status: "running" }));
    fetchMock.mockResolvedValueOnce(operation({ status: "succeeded", result: article }));

    const { settled } = startDraft("draft-key");
    await vi.runAllTimersAsync();

    expect(await settled).toEqual({ ok: true, value: article });
    expect(pollsOf("op-draft")).toHaveLength(3);
  });

  it("surfaces a failed operation and stops polling immediately", async () => {
    fetchMock.mockResolvedValueOnce(accepted());
    fetchMock.mockResolvedValue(
      operation({
        status: "failed",
        error: { code: "SOURCE_UNAVAILABLE", message: "Източникът временно не е наличен.", retryable: true },
      }),
    );

    const { settled } = startDraft("draft-key");
    await vi.runAllTimersAsync();

    const outcome = await settled;
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.error).toEqual(
        expect.objectContaining({ code: "SOURCE_UNAVAILABLE", retryable: true }),
      );
    }
    // One poll is enough: a terminal failure is not retried.
    expect(pollsOf("op-draft")).toHaveLength(1);
  });

  it("stops at the bounded budget and reports a truthful transport message", async () => {
    fetchMock.mockResolvedValueOnce(accepted());
    // The backend operation never settles within the client budget.
    fetchMock.mockResolvedValue(operation({ status: "running" }));

    const { settled } = startDraft("draft-key");
    await vi.runAllTimersAsync();

    const outcome = await settled;
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.error.message).toBe("Черновата все още се създава. Опитайте отново след малко.");
    }
    expect(pollsOf("op-draft")).toHaveLength(DRAFT_POLL_BUDGET.attempts);
  });

  it("never implies that generation failed when the budget is exhausted", async () => {
    fetchMock.mockResolvedValueOnce(accepted());
    fetchMock.mockResolvedValue(operation({ status: "running" }));

    const { settled } = startDraft("draft-key");
    await vi.runAllTimersAsync();
    const outcome = await settled;

    // The old wording claimed the Draft simply was not ready; the new wording
    // states that generation is still under way, and stays retryable.
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.error.message).not.toMatch(/не можа|не е готова/i);
      expect(outcome.error.retryable).toBe(true);
    }
  });

  it("does not start a second generation while polling one operation", async () => {
    fetchMock.mockResolvedValueOnce(accepted());
    for (let poll = 0; poll < 5; poll += 1) {
      fetchMock.mockResolvedValueOnce(operation({ status: "running" }));
    }
    fetchMock.mockResolvedValueOnce(operation({ status: "succeeded", result: article }));

    const { settled } = startDraft("draft-key");
    await vi.runAllTimersAsync();
    expect(await settled).toEqual({ ok: true, value: article });

    const posts = fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    );
    // Exactly one POST: repeated polls must never re-trigger generation.
    expect(posts).toHaveLength(1);
    // And it keeps the caller-supplied Idempotency-Key, unchanged by polling.
    expect((posts[0]?.[1] as RequestInit).headers).toEqual(
      expect.objectContaining({ "Idempotency-Key": "draft-key" }),
    );
  });

  it("preserves the Idempotency-Key when the operation is polled", async () => {
    fetchMock.mockResolvedValueOnce(accepted("op-keyed"));
    fetchMock.mockResolvedValueOnce(operation({ status: "running" }));
    fetchMock.mockResolvedValueOnce(operation({ status: "succeeded", result: article }));

    const { settled } = startDraft("stable-key");
    await vi.runAllTimersAsync();
    expect(await settled).toEqual({ ok: true, value: article });

    const posts = fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    );
    expect(posts).toHaveLength(1);
    expect((posts[0]?.[1] as RequestInit).headers).toEqual(
      expect.objectContaining({ "Idempotency-Key": "stable-key" }),
    );
  });
});
