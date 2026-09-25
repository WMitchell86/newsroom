import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, followStory, getArticles, getToday, ignoreStory, researchMoreStory, reviewStory, unfollowStory } from "../api/client";
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
