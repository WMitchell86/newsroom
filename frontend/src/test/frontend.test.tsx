import { screen, waitFor, within } from "@testing-library/react";
import { queryKeys, storiesOptions, todayOptions } from "../api/queries";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../app/AppShell";
import { ArticleListPage } from "../pages/ArticleListPage";
import { ArticleWorkspace } from "../pages/ArticleWorkspace";
import { ArchivePage } from "../pages/ArchivePage";
import { SettingsLanding } from "../pages/SettingsLanding";
import { StoryListPage } from "../pages/StoryListPage";
import { StoryWorkspace } from "../pages/StoryWorkspace";
import { TodayPage } from "../pages/TodayPage";
import {
  activeDraftArticle,
  activePreparationArticle,
  activeReadyArticle,
  finalizedArchiveArticle,
  storyDetail,
  todayProjection,
} from "./fixtures";
import { renderWithProviders } from "./render";

import type { ArticleDetail, StoryDetail } from "../api/dto";
function errorResponse(code: string, message: string, status: number, retryable = false) {
  return {
    ok: false,
    status,
    json: async () => ({ error: { code, message, retryable, fieldErrors: [] } }),
  } as Response;
}

function storyRoute() {
  return (
    <Routes>
      <Route path="/stories/:storyId" element={<StoryWorkspace />} />
      <Route path="/articles/:articleId" element={<ArticleWorkspace />} />
    </Routes>
  );
}

const fetchMock = vi.fn();

function dataResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ data }),
  } as Response;
}

function articleListResponse() {
  return { articles: [activePreparationArticle, activeDraftArticle, activeReadyArticle] };
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});
describe("AppShell navigation", () => {
  it("has exactly five primary areas, no left rail, and marks the current area", () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="stories" element={<p>Истории</p>} />
        </Route>
      </Routes>,
      { initialEntries: ["/stories"] },
    );

    const navigation = screen.getByRole("navigation", { name: "Основни раздели" });
    const links = within(navigation).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Днес", "Истории", "Статии", "Архив", "Настройки"]);
    expect(within(navigation).getByRole("link", { name: "Истории" })).toHaveAttribute("aria-current", "page");
    expect(document.querySelector("aside")).toBeNull();
    expect(document.querySelector("nav")).not.toHaveAttribute("data-orientation", "vertical");
  });
});

describe("Today", () => {
  it("renders all attention groups as links without issuing mutations", async () => {
    fetchMock.mockResolvedValue(dataResponse(todayProjection));
    renderWithProviders(<TodayPage />, { route: "/" });

    await screen.findByRole("heading", { name: "Днес" });
    expect(screen.getByRole("heading", { name: "Нови развития" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Нови истории" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Статии за действие" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Проблеми" })).toBeInTheDocument();
    const storyLinks = screen.getAllByRole("link", { name: storyDetail.title });
    expect(storyLinks.some((link) => link.getAttribute("href") === `/stories/${storyDetail.id}`)).toBe(true);
    const articleLinks = screen.getAllByRole("link", { name: activeDraftArticle.title });
    expect(articleLinks.some((link) => link.getAttribute("href") === `/articles/${activeDraftArticle.id}`)).toBe(true);
    expect(screen.getByRole("link", { name: "Липсва потвърждение" })).toHaveAttribute("href", "/settings/sources");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.every(([, init]) => !("method" in (init ?? {})) || init.method === "GET")).toBe(true);
  });

  it("renders the real Обнови action and keeps the internal stages invisible", async () => {
    fetchMock.mockResolvedValue(dataResponse(todayProjection));
    renderWithProviders(<TodayPage />, { route: "/" });

    await screen.findByRole("heading", { name: "Днес" });
    expect(screen.getByRole("button", { name: "Обнови" })).toBeEnabled();
    // A query refetch is not the newsroom action, and no stage is exposed.
    expect(screen.queryByRole("button", { name: "Обнови" })).not.toBeDisabled();
    for (const stage of ["Събиране", "Скрапване", "Ingest", "Групиране", "Класификация", "Модел"]) {
      expect(screen.queryByText(stage)).toBeNull();
    }
  });

  it("runs one refresh, polls the operation and refetches Today and Stories", async () => {
    const refreshed = {
      ...todayProjection,
      newStories: [
        {
          objectId: "s-fresh",
          objectType: "story" as const,
          title: "Нова история след обновяване",
          summary: "Материалът дойде от източника.",
          timestamp: "2026-09-25T11:00:00Z",
          reason: "NEW_STORY" as const,
          nextAction: "REVIEW" as const,
          delta: { unreviewedDevelopmentCount: 0 },
        },
      ],
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-refresh" } }) } as Response;
      }
      if (url === "/api/v1/operations/op-refresh") return dataResponse({ status: "succeeded" });
      if (url.startsWith("/api/v1/stories")) return dataResponse({ stories: [] });
      return dataResponse(refreshed);
    });
    const user = userEvent.setup();
    const { queryClient } = renderWithProviders(<TodayPage />, { route: "/" });
    // A cached Story list projection, as the editor would have after visiting
    // «Истории»: the refresh must invalidate it, not just Today.
    await queryClient.prefetchQuery(storiesOptions("all", ""));
    await screen.findByRole("heading", { name: "Днес" });

    await user.click(screen.getByRole("button", { name: "Обнови" }));

    expect(await screen.findByRole("link", { name: "Нова история след обновяване" })).toBeInTheDocument();
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.[0]).toBe("/api/v1/today/refresh");
    expect((posts[0]?.[1] as RequestInit).headers).toEqual(
      expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
    );
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/v1/operations/op-refresh")).toBe(true);
    // Canonical refetch: Today and the Story list projections, nothing else.
    const urls = fetchMock.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === "/api/v1/today").length).toBeGreaterThan(1);
    expect(urls.some((url) => String(url).startsWith("/api/v1/stories"))).toBe(true);
  });

  it("keeps Today visible and prevents a duplicate click while refreshing", async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { release = resolve; });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-slow" } }) } as Response;
      }
      if (url === "/api/v1/operations/op-slow") return pending;
      return dataResponse(todayProjection);
    });
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });
    const before = screen.getByRole("link", { name: activeDraftArticle.title });

    await user.click(screen.getByRole("button", { name: "Обнови" }));
    const button = await screen.findByRole("button", { name: "Обновява се…" });
    expect(button).toBeDisabled();
    // The existing attention content is still on screen, not a blank loader.
    expect(screen.getByRole("link", { name: activeDraftArticle.title })).toBe(before);
    await user.click(button).catch(() => undefined);

    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts).toHaveLength(1);

    release(dataResponse({ status: "succeeded" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Обнови" })).toBeEnabled());
  });

  it("keeps Today intact and shows a point-of-action error when the refresh fails", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return errorResponse("SOURCE_UNAVAILABLE", "Новините не можаха да се обновят.", 503);
      }
      return dataResponse(todayProjection);
    });
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    await user.click(screen.getByRole("button", { name: "Обнови" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Новините не можаха да се обновят.");
    // The newsroom content is untouched and a retry stays possible.
    expect(screen.getByRole("link", { name: activeDraftArticle.title })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Обнови" })).toBeEnabled();
  });

  it("renders a partial-success problem canonically after a refresh", async () => {
    const withProblem = {
      ...todayProjection,
      problems: [
        {
          id: "problem_abc",
          title: "Източникът „Огледало“ не се обнови",
          consequence: "Източникът е работил, но при последното обновяване не е дал материал.",
          label: "Прегледай източниците",
          target: "/settings",
        },
      ],
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-partial" } }) } as Response;
      }
      if (url === "/api/v1/operations/op-partial") return dataResponse({ status: "succeeded", result: { new: 1, failedSources: 1 } });
      return dataResponse(withProblem);
    });
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    await user.click(screen.getByRole("button", { name: "Обнови" }));

    expect(await screen.findByRole("heading", { name: "Източникът „Огледало“ не се обнови" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Прегледай източниците" })).toHaveAttribute("href", "/settings");
  });
});

describe("Stories", () => {
  it("exposes exactly the four filters and sends the selected filter and query to the API", async () => {
    fetchMock.mockResolvedValue(dataResponse({ stories: [] }));
    renderWithProviders(<StoryListPage />, { initialEntries: ["/stories?filter=developments&q=%D0%B1%D1%8E%D0%B4%D0%B6%D0%B5%D1%82%D0%B0"] });

    const filters = screen.getByRole("navigation", { name: "Филтри за истории" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(within(filters).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Всички",
      "Следени",
      "Нови развития",
      "Игнорирани",
    ]);
    expect(within(filters).getByRole("link", { name: "Нови развития" })).toHaveAttribute("aria-current", "page");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/stories?filter=developments&query=%D0%B1%D1%8E%D0%B4%D0%B6%D0%B5%D1%82%D0%B0",
      expect.objectContaining({ credentials: "same-origin", headers: { Accept: "application/json" } }),
    );
  });

  it("does not render internal fields returned with a Story detail", async () => {
    fetchMock.mockResolvedValue(dataResponse({ ...storyDetail, internal_refs: ["idea:secret"], idea_id: "secret", content_path: "/private/path" }));
    renderWithProviders(
      <Routes>
        <Route path="/stories/:storyId" element={<StoryWorkspace />} />
      </Routes>,
      { initialEntries: [`/stories/${storyDetail.id}`] },
    );

    await screen.findByRole("heading", { name: storyDetail.title });
    expect(screen.queryByText("idea:secret")).toBeNull();
    expect(screen.queryByText("secret")).toBeNull();
    expect(screen.queryByText("/private/path")).toBeNull();
  });

  it("renders canonical Story title plus safe facts and gaps from a read-only detail response", async () => {
    fetchMock.mockResolvedValue(dataResponse(storyDetail));
    renderWithProviders(
      <Routes>
        <Route path="/stories/:storyId" element={<StoryWorkspace />} />
      </Routes>,
      { initialEntries: [`/stories/${storyDetail.id}`] },
    );

    await screen.findByRole("heading", { level: 1, name: storyDetail.title });
    expect(screen.getByRole("heading", { name: "Факти и източници" })).toBeInTheDocument();
    expect(screen.getByText(storyDetail.factsAndSources![0]!.text)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Какво липсва" })).toBeInTheDocument();
    expect(screen.getByText(storyDetail.missingInformation!.items[0]!.question)).toBeVisible();
    expect(screen.getByText(storyDetail.missingInformation!.items[0]!.reason!)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Проучи още" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/stories/${storyDetail.id}`, expect.objectContaining({ credentials: "same-origin" }));
    expect(fetchMock.mock.calls.every(([, init]) => !("method" in (init ?? {})) || init.method === "GET")).toBe(true);
  });
});

describe("B4A RESEARCH_MORE", () => {
  const researchStory: StoryDetail = {
    ...storyDetail,
    availableActions: ["RESEARCH_MORE"],
    missingInformation: { items: [{ id: "gap-1", question: "Кога е официалният график?", kind: "missing_fact", blocking: true }], assessedAt: null },
  };

  function renderResearch() {
    const user = userEvent.setup();
    const result = renderWithProviders(storyRoute(), { initialEntries: [`/stories/${researchStory.id}`] });
    return { user, ...result };
  }

  it("renders only when authorized, submits once on double click, and retains content while invalidating projections", async () => {
    let researchCalls = 0;
    let resolveResearch!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { resolveResearch = resolve; });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url === `/api/v1/stories/${researchStory.id}/research`) {
        researchCalls += 1;
        return pending;
      }
      return dataResponse(researchStory);
    });
    const { user, queryClient } = renderResearch();
    const button = await screen.findByRole("button", { name: "Проучи още" });
    expect(screen.getByText("Кога е официалният график?")).toBeVisible();
    await user.dblClick(button);
    expect(await screen.findByRole("button", { name: "Проучва се…" })).toBeDisabled();
    expect(researchCalls).toBe(1);
    expect(screen.getByRole("heading", { level: 1, name: researchStory.title })).toBeInTheDocument();
    queryClient.setQueryData(queryKeys.today, todayProjection);
    queryClient.setQueryData(queryKeys.stories("all", ""), { stories: [researchStory] });
    resolveResearch(dataResponse(researchStory));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === `/api/v1/stories/${researchStory.id}` && !(init as RequestInit | undefined)?.method)).toBe(true));
    expect(queryClient.getQueryState(queryKeys.today)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.stories("all", ""))?.isInvalidated).toBe(true);
  });

  it("completes a 202 research operation and refreshes the Story content", async () => {
    const refreshed = { ...researchStory, title: "Обновена история" };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url === `/api/v1/stories/${researchStory.id}/research`) {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-ui" } }) } as Response;
      }
      if (url === "/api/v1/operations/op-ui") return dataResponse({ status: "succeeded", result: refreshed });
      return dataResponse(refreshed);
    });
    const { user } = renderResearch();
    await user.click(await screen.findByRole("button", { name: "Проучи още" }));
    expect(await screen.findByRole("heading", { level: 1, name: refreshed.title })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/operations/op-ui", expect.objectContaining({ credentials: "same-origin" }));
    const researchCall = fetchMock.mock.calls.find(([url, init]) => url === `/api/v1/stories/${researchStory.id}/research` && (init as RequestInit)?.method === "POST");
    expect((researchCall?.[1] as RequestInit).headers).toEqual(expect.objectContaining({ "Idempotency-Key": expect.any(String) }));
  });

  it("shows an async failure near the gaps and exposes no Research route or stages", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url === `/api/v1/stories/${researchStory.id}/research`) {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-ui-fail" } }) } as Response;
      }
      if (url === "/api/v1/operations/op-ui-fail") return dataResponse({ status: "failed", error: { code: "SOURCE_UNAVAILABLE", message: "Източникът временно не е наличен.", retryable: true } });
      return dataResponse(researchStory);
    });
    const { user } = renderResearch();
    await user.click(await screen.findByRole("button", { name: "Проучи още" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Източникът временно не е наличен.");
    expect(screen.getByText("Кога е официалният график?")).toBeVisible();
    expect(screen.queryByText(/Research|Research|Етап/)).toBeNull();
    expect(fetchMock.mock.calls.every(([url, init]) => !(init as RequestInit | undefined)?.method || (init as RequestInit).method === "GET" || url.endsWith("/research"))).toBe(true);
  });
});

describe("B3 Story actions", () => {
  const initialA: StoryDetail = {
    ...storyDetail,
    reviewed: false,
    followed: false,
    availableActions: ["REVIEW", "FOLLOW", "IGNORE"],
    unreviewedDevelopmentCount: 2,
    newDevelopments: [
      { id: "development-budget-1", publicationId: "publication-budget-1", title: "А", summary: "А", changedAt: "2026-09-25T08:00:00Z", unreviewed: true },
      { id: "development-budget-2", publicationId: "publication-budget-2", title: "Б", summary: "Б", changedAt: "2026-09-25T09:30:00Z", unreviewed: true },
    ],
  };

  function renderStory(detail: StoryDetail) {
    const user = userEvent.setup();
    const result = renderWithProviders(storyRoute(), { initialEntries: [`/stories/${detail.id}`] });
    return { user, ...result };
  }

  it("submits exactly the A/B snapshot observed at render, then refetches C as unreviewed attention", async () => {
    let canonical = initialA;
    let requestBody: unknown;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/review")) {
        requestBody = JSON.parse(String(init.body));
        canonical = { ...canonical, reviewed: true, followed: true, unreviewedDevelopmentCount: 1, availableActions: ["UNFOLLOW", "IGNORE"], newDevelopments: [
          { ...initialA.newDevelopments[0]!, unreviewed: false },
          { ...initialA.newDevelopments[1]!, unreviewed: false },
          { id: "development-c", publicationId: "publication-c", title: "В", summary: "В", changedAt: "2026-09-25T10:00:00Z", unreviewed: true },
        ] };
        return dataResponse(canonical);
      }
      if (url === `/api/v1/stories/${storyDetail.id}`) return dataResponse(canonical);
      if (url === "/api/v1/today") return dataResponse({ ...todayProjection, newDevelopments: [{ objectId: storyDetail.id, objectType: "story", title: canonical.title, summary: canonical.summary, timestamp: "2026-09-25T10:00:00Z", reason: "UNREVIEWED_DEVELOPMENT", nextAction: "REVIEW", delta: { unreviewedDevelopmentCount: 1 } }] });
      if (url.startsWith("/api/v1/stories?")) return dataResponse({ stories: [canonical] });
      throw new Error(`Unexpected URL ${url}`);
    });

    const { user, queryClient } = renderStory(initialA);
    queryClient.setQueryData(queryKeys.today, todayProjection);
    queryClient.setQueryData(queryKeys.stories("all", ""), { stories: [initialA] });
    await screen.findByRole("heading", { name: "А" });
    canonical = { ...canonical, newDevelopments: [...canonical.newDevelopments, { id: "development-c", publicationId: "publication-c", title: "В", summary: "В", changedAt: "2026-09-25T10:00:00Z", unreviewed: true }] };

    await user.click(screen.getByRole("button", { name: "Прегледай" }));
    await waitFor(() => expect(requestBody).toEqual({ observedDevelopmentIds: ["development-budget-1", "development-budget-2"] }));
    expect(await screen.findByRole("heading", { name: "В" })).toBeInTheDocument();
    expect(queryClient.getQueryState(queryKeys.today)?.isInvalidated).toBe(true);
    const refreshedToday = await queryClient.fetchQuery(todayOptions());
    const refreshedStory = refreshedToday.newDevelopments.find((item) => item.objectType === "story");
    expect(refreshedStory?.objectType === "story" ? refreshedStory.delta.unreviewedDevelopmentCount : 0).toBe(1);
    expect(queryClient.getQueryState(queryKeys.stories("all", ""))?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.stories("all", ""))?.isInvalidated).toBe(true);
  });

  it("reviews a plain new Story with an empty observed set", async () => {
    const plain: StoryDetail = { ...initialA, reviewed: false, unreviewedDevelopmentCount: 0, availableActions: ["REVIEW", "FOLLOW", "IGNORE"], newDevelopments: [] };
    let submitted: unknown;
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        submitted = JSON.parse(String(init.body));
        return dataResponse({ ...plain, reviewed: true, availableActions: ["FOLLOW", "IGNORE"] });
      }
      return dataResponse(plain);
    });
    const { user } = renderStory(plain);
    await user.click(await screen.findByRole("button", { name: "Прегледай" }));
    await waitFor(() => expect(submitted).toEqual({ observedDevelopmentIds: [] }));
  });
  it("uses canonical commands for follow, unfollow, and ignore and refreshes the detail", async () => {
    let canonical: StoryDetail = { ...initialA, availableActions: ["FOLLOW", "IGNORE"] };
    const calls: Array<[string, string | undefined]> = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      calls.push([url, init?.method]);
      if (init?.method === "PUT") canonical = { ...canonical, followed: true, availableActions: ["REVIEW", "UNFOLLOW", "IGNORE"] };
      if (init?.method === "DELETE") canonical = { ...canonical, followed: false, availableActions: ["REVIEW", "FOLLOW", "IGNORE"] };
      if (init?.method === "POST" && url.endsWith("/ignore")) canonical = { ...canonical, ignored: true, availableActions: ["REVIEW", "UNFOLLOW"] };
      return dataResponse(canonical);
    });
    const { user } = renderStory(canonical);
    await user.click(await screen.findByRole("button", { name: "Следи" }));
    expect(await screen.findByRole("button", { name: "Спри следването" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Спри следването" }));
    expect(await screen.findByRole("button", { name: "Следи" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Игнорирай" }));
    expect(await screen.findByText(/Тази история е извън фокуса/)).toBeInTheDocument();
    expect(calls).toEqual(expect.arrayContaining([
      [`/api/v1/stories/${storyDetail.id}/follow`, "PUT"],
      [`/api/v1/stories/${storyDetail.id}/follow`, "DELETE"],
      [`/api/v1/stories/${storyDetail.id}/ignore`, "POST"],
    ]));
  });

  it("keeps deferred controls noninteractive and does not label a query refetch as the future Обнови", async () => {
    fetchMock.mockResolvedValue(dataResponse({ ...storyDetail, availableActions: ["RESEARCH_MORE"] }));
    renderStory({ ...storyDetail, availableActions: ["RESEARCH_MORE"] });
    expect(await screen.findByRole("button", { name: "Проучи още" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Обнови" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Започни статия" })).toBeNull();
    expect(fetchMock.mock.calls.every(([, init]) => !init.method || init.method === "GET")).toBe(true);
  });

  it("keeps the current command pending without duplicate submission and leaves the Story readable", async () => {
    let resolveMutation!: (response: Response) => void;
    const pendingResponse = new Promise<Response>((resolve) => { resolveMutation = resolve; });
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => init?.method === "POST" ? pendingResponse : dataResponse(initialA));
    const { user } = renderStory(initialA);
    const review = await screen.findByRole("button", { name: "Прегледай" });
    await user.click(review);
    expect(await screen.findByRole("button", { name: "Преглежда се…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Следи" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Игнорирай" })).toBeDisabled();
    expect(screen.getByRole("heading", { name: "А" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Преглежда се…" }));
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    resolveMutation(dataResponse({ ...initialA, reviewed: true, availableActions: ["FOLLOW", "IGNORE"] }));
  });

  it("recovers an ignored followed Story through the existing Review action", async () => {
    const ignored: StoryDetail = { ...initialA, ignored: true, followed: true, reviewed: true, unreviewedDevelopmentCount: 0, newDevelopments: [], availableActions: ["REVIEW", "UNFOLLOW"] };
    let canonical = ignored;
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        canonical = { ...canonical, ignored: false, availableActions: ["UNFOLLOW"] };
        return dataResponse(canonical);
      }
      return dataResponse(canonical);
    });
    const { user } = renderStory(ignored);
    expect(await screen.findByText("Игнорирана")).toBeInTheDocument();
    expect(screen.getByText("Следена: да")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Прегледай" }));
    await waitFor(() => expect(screen.queryByText(/Тази история е извън фокуса/)).toBeNull());
    expect(screen.queryByText("Игнорирана")).toBeNull();
    expect(screen.getByText("Следена: да")).toBeInTheDocument();
  });

  it("keeps the Story and visible developments on rejection and shows a point-of-action error", async () => {
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => init?.method === "POST"
      ? errorResponse("INVALID_TRANSITION", "Действието вече не е налично.", 409)
      : dataResponse(initialA));
    const { user } = renderStory(initialA);
    await user.click(await screen.findByRole("button", { name: "Прегледай" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Действието вече не е налично.");
    expect(screen.getByRole("heading", { name: "А" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Б" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Прегледай" })).toBeEnabled();
  });

  it("uses availableActions as policy and keeps list rows navigation-only", async () => {
    fetchMock.mockResolvedValue(dataResponse({ ...storyDetail, availableActions: ["UNFOLLOW"] }));
    renderStory({ ...storyDetail, availableActions: ["UNFOLLOW"] });
    expect(await screen.findByRole("button", { name: "Спри следването" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Прегледай" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Игнорирай" })).toBeNull();
    fetchMock.mockResolvedValue(dataResponse({ stories: [storyDetail] }));
    renderWithProviders(<StoryListPage />, { initialEntries: ["/stories"] });
    await screen.findByRole("link", { name: storyDetail.title });
    expect(screen.queryByRole("button", { name: /Прегледай|Следи|Игнорирай/ })).toBeNull();
  });
});

describe("C1 Start Article", () => {
  it("shows the real action only from backend policy, prevents pending duplicates, refetches and navigates", async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { release = resolve; });
    const detail = { ...storyDetail, availableActions: ["UNFOLLOW", "START_ARTICLE"] as StoryDetail["availableActions"] };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url === `/api/v1/stories/${storyDetail.id}/articles`) return pending;
      if (url === `/api/v1/stories/${storyDetail.id}`) return dataResponse(detail);
      if (url === `/api/v1/articles/${activePreparationArticle.id}`) return dataResponse(activePreparationArticle);
      if (url.startsWith("/api/v1/articles?")) return dataResponse({ articles: [activePreparationArticle] });
      if (url === "/api/v1/today") return dataResponse(todayProjection);
      throw new Error(`Unexpected URL ${url}`);
    });
    const user = userEvent.setup();
    const { queryClient } = renderWithProviders(storyRoute(), { initialEntries: [`/stories/${storyDetail.id}`] });
    queryClient.setQueryData(queryKeys.articles("all", ""), { articles: [] });
    queryClient.setQueryData(queryKeys.articles("preparation", ""), { articles: [] });
    queryClient.setQueryData(queryKeys.today, todayProjection);

    await user.click(await screen.findByRole("button", { name: "Започни статия" }));
    const pendingButton = await screen.findByRole("button", { name: "Започва се…" });
    expect(pendingButton).toBeDisabled();
    await user.click(pendingButton).catch(() => undefined);
    expect(fetchMock.mock.calls.filter(([url, init]) => url === `/api/v1/stories/${storyDetail.id}/articles` && init?.method === "POST")).toHaveLength(1);

    release(dataResponse(activePreparationArticle, 201));
    expect(await screen.findByRole("heading", { level: 1, name: activePreparationArticle.title })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Редакционен фокус" })).toBeInTheDocument();
    expect(queryClient.getQueryState(queryKeys.articles("all", ""))?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.articles("preparation", ""))?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.today)?.isInvalidated).toBe(true);
  });

  it("stays on a readable Story on failure and reuses the same retry key", async () => {
    const detail = { ...storyDetail, availableActions: ["START_ARTICLE"] as StoryDetail["availableActions"] };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/articles")) return errorResponse("INTERNAL_ERROR", "Статията не може да бъде създадена.", 500);
      return dataResponse(detail);
    });
    const user = userEvent.setup();
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${storyDetail.id}`] });

    await user.click(await screen.findByRole("button", { name: "Започни статия" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Статията не може да бъде създадена.");
    expect(screen.getByRole("heading", { level: 1, name: storyDetail.title })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Започни статия" }));

    const posts = fetchMock.mock.calls.filter(([url, init]) => url.endsWith("/articles") && init?.method === "POST");
    const firstKey = (posts[0]?.[1] as RequestInit).headers as Record<string, string>;
    const retryKey = (posts[1]?.[1] as RequestInit).headers as Record<string, string>;
    expect(posts).toHaveLength(2);
    expect(firstKey["Idempotency-Key"]).toBe(retryKey["Idempotency-Key"]);
  });

  it("does not render Start Article when it is absent from availableActions", async () => {
    fetchMock.mockResolvedValue(dataResponse({ ...storyDetail, availableActions: ["UNFOLLOW"] }));
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${storyDetail.id}`] });
    await screen.findByRole("heading", { level: 1, name: storyDetail.title });
    expect(screen.queryByRole("button", { name: "Започни статия" })).toBeNull();
  });
});

describe("Articles", () => {
  it("shows exactly the three active state labels alongside the all option and keeps the canonical Story title", async () => {
    fetchMock.mockResolvedValue(dataResponse(articleListResponse()));
    renderWithProviders(<ArticleListPage />, { initialEntries: ["/articles?filter=all"] });
    await screen.findByRole("link", { name: activeDraftArticle.title });
    const filters = screen.getByRole("navigation");
    expect(within(filters).getAllByRole("button").map((button) => button.textContent)).toEqual(["Всички", "Подготовка", "Чернова", "Готова"]);
    expect(screen.getAllByRole("link", { name: storyDetail.title }).length).toBeGreaterThan(0);
  });

  it("uses the URL-backed Article search and sends both query and filter to a read-only fetch", async () => {
    fetchMock.mockResolvedValue(dataResponse(articleListResponse()));
    renderWithProviders(<ArticleListPage />, {
      initialEntries: [`/articles?filter=draft&q=${encodeURIComponent("булевард")}`],
    });

    const search = screen.getByRole("searchbox", { name: "Търсене по заглавие и текст" }) as HTMLInputElement;
    expect(search).toBeEnabled();
    expect(search).toHaveValue("булевард");
    const filters = screen.getByRole("navigation");
    expect(within(filters).getByRole("button", { name: "Чернова" })).toHaveAttribute("aria-pressed", "true");

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/articles?filter=draft&query=%D0%B1%D1%83%D0%BB%D0%B5%D0%B2%D0%B0%D1%80%D0%B4",
      expect.objectContaining({ credentials: "same-origin", headers: { Accept: "application/json" } }),
    ));
    expect(fetchMock.mock.calls.every(([, init]) => !("method" in (init ?? {})) || init.method === "GET")).toBe(true);
  });

  it("renders Preparation as an editor surface without a Draft body and consumes backend eligibility", async () => {
    fetchMock.mockResolvedValue(dataResponse(activePreparationArticle));
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );

    expect(await screen.findByText("Подготовка", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Редакционен фокус" })).toHaveValue(activePreparationArticle.editorialFocus.text);
    expect(screen.getByText("Фокусът е предложение и очаква редакторско решение.")).toBeInTheDocument();
    expect(screen.getByText(activePreparationArticle.factsAndSources[0]!.text)).toBeInTheDocument();
    expect(screen.getByText(activePreparationArticle.preparation!.nonBlockingGaps[0]!.question)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Чернова" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /текст на статията/i })).toBeNull();
  });

  it("persists working title on blur and focus confirmation through canonical projections", async () => {
    let canonical = { ...activePreparationArticle };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/title")) {
        canonical = { ...canonical, title: "Ново работно заглавие", content: { ...canonical.content, title: "Ново работно заглавие", version: 1 } };
        return dataResponse(canonical);
      }
      if (init?.method === "PUT" && url.endsWith("/focus")) {
        const body = JSON.parse(String(init.body)) as { focus: string };
        canonical = {
          ...canonical,
          editorialFocus: { text: body.focus, confirmedAt: "2026-09-25T11:00:00Z" },
          preparation: { ...canonical.preparation!, focusConfirmed: true, draftEligible: true, availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"] },
          availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"],
          nextAction: { action: "MAKE_DRAFT", reasonCode: "DRAFT_ELIGIBLE", label: "Направи чернова", primary: true },
        };
        return dataResponse(canonical);
      }
      return dataResponse(canonical);
    });
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );
    const title = await screen.findByRole("textbox", { name: "Работно заглавие" });
    await user.clear(title);
    await user.type(title, "Ново работно заглавие");
    await user.tab();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/articles/${activePreparationArticle.id}/title`,
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ expectedVersion: 0, title: "Ново работно заглавие" }) }),
    ));

    const focus = screen.getByRole("textbox", { name: "Редакционен фокус" });
    await user.clear(focus);
    await user.type(focus, "Обясняваме промяната и последиците.");
    await user.click(screen.getByRole("button", { name: "Избери фокус" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/articles/${activePreparationArticle.id}/focus`,
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ focus: "Обясняваме промяната и последиците." }) }),
    ));
    expect(await screen.findByRole("button", { name: "Промени фокуса" })).toBeInTheDocument();
    expect(screen.getByText(/Фокусът е потвърден и няма блокиращи липси/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Направи чернова" })).toBeInTheDocument();
  });

  it("renders MAKE_DRAFT only when the backend authorizes it and the Article is eligible", async () => {
    const eligible = {
      ...activePreparationArticle,
      editorialFocus: { ...activePreparationArticle.editorialFocus, confirmedAt: "2026-09-25T11:00:00Z" },
      preparation: { ...activePreparationArticle.preparation!, focusConfirmed: true, draftEligible: true, availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"] },
      availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"],
    };
    fetchMock.mockResolvedValue(dataResponse(eligible));
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${eligible.id}`] },
    );

    expect(await screen.findByRole("button", { name: "Направи чернова" })).toBeEnabled();
    expect(screen.queryByRole("textbox", { name: /текст на статията/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Редактирай|Финализирай/ })).toBeNull();
  });

  it("creates a draft once, shows pending wording, and adopts the canonical read-only Draft", async () => {
    const eligible = {
      ...activePreparationArticle,
      editorialFocus: { ...activePreparationArticle.editorialFocus, confirmedAt: "2026-09-25T11:00:00Z" },
      preparation: { ...activePreparationArticle.preparation!, focusConfirmed: true, draftEligible: true, availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"] },
      availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"],
    };
    const generated: ArticleDetail = { ...activeDraftArticle, id: eligible.id, story: eligible.story, title: eligible.title, preparation: null, editorialFocus: { ...activeDraftArticle.editorialFocus, confirmedAt: "2026-09-25T11:00:00Z" }, warnings: [{ id: "warning-1", severity: "review", message: "Проверете цитата.", blocking: false }] };
    let resolveDraft!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { resolveDraft = resolve; });
    let canonical: ArticleDetail = eligible as ArticleDetail;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/draft")) return pending;
      return dataResponse(canonical);
    });
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${eligible.id}`] },
    );

    const button = await screen.findByRole("button", { name: "Направи чернова" });
    await user.click(button);
    expect(await screen.findByRole("button", { name: "Черновата се създава…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Черновата се създава…" }));
    expect(fetchMock.mock.calls.filter(([url, init]) => url.endsWith("/draft") && init?.method === "POST")).toHaveLength(1);
    canonical = generated;
    resolveDraft(dataResponse(generated));

    expect(await screen.findByRole("heading", { name: "Чернова" })).toBeInTheDocument();
    expect(screen.getByText(generated.content.body)).toBeInTheDocument();
    expect(screen.getByText("Проверете цитата.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /текст на статията/i })).toBeNull();
  });

  it("keeps preparation and only offers retry after a retryable draft failure", async () => {
    const eligible = {
      ...activePreparationArticle,
      editorialFocus: { ...activePreparationArticle.editorialFocus, confirmedAt: "2026-09-25T11:00:00Z" },
      preparation: { ...activePreparationArticle.preparation!, focusConfirmed: true, draftEligible: true, availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"] },
      availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"],
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => init?.method === "POST" && url.endsWith("/draft")
      ? errorResponse("SOURCE_UNAVAILABLE", "Източникът временно не е наличен.", 503, true)
      : dataResponse(eligible));
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${eligible.id}`] },
    );
    await user.click(await screen.findByRole("button", { name: "Направи чернова" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Източникът временно не е наличен.");
    expect(screen.getByRole("button", { name: "Направи чернова" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: "Чернова" })).toBeNull();
  });

  it("does not offer a retry for a non-retryable draft failure", async () => {
    const eligible = {
      ...activePreparationArticle,
      editorialFocus: { ...activePreparationArticle.editorialFocus, confirmedAt: "2026-09-25T11:00:00Z" },
      preparation: { ...activePreparationArticle.preparation!, focusConfirmed: true, draftEligible: true, availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"] },
      availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"],
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => init?.method === "POST" && url.endsWith("/draft")
      ? errorResponse("SAFETY_BLOCKED", "Проверката за безопасност спря операцията.", 409)
      : dataResponse(eligible));
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${eligible.id}`] },
    );
    await user.click(await screen.findByRole("button", { name: "Направи чернова" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Проверката за безопасност спря операцията.");
    expect(screen.getByRole("button", { name: "Направи чернова" })).toBeDisabled();
  });
  it("preserves locally typed preparation fields when canonical updates fail", async () => {
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => init?.method === "PUT"
      ? errorResponse("INTERNAL_ERROR", "Записът не е завършен.", 500)
      : dataResponse(activePreparationArticle));
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );
    const focus = await screen.findByRole("textbox", { name: "Редакционен фокус" });
    await user.clear(focus);
    await user.type(focus, "Локален текст, който не трябва да изчезне.");
    await user.click(screen.getByRole("button", { name: "Избери фокус" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Записът не е завършен.");
    expect(focus).toHaveValue("Локален текст, който не трябва да изчезне.");
    expect(screen.getByText("Фокусът е предложение и очаква редакторско решение.")).toBeInTheDocument();
  });

  it("refetches canonical version after a title conflict while preserving local text", async () => {
    const canonical = { ...activePreparationArticle, content: { ...activePreparationArticle.content, version: 1 } };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/title")) {
        return errorResponse("ARTICLE_VERSION_CONFLICT", "Заглавието е променено в друга сесия.", 409);
      }
      return dataResponse(canonical);
    });
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );
    const title = await screen.findByRole("textbox", { name: "Работно заглавие" });
    await user.clear(title);
    await user.type(title, "Локален текст след конфликт");
    await user.tab();

    expect(await screen.findByRole("alert")).toHaveTextContent("Заглавието е променено в друга сесия.");
    expect(title).toHaveValue("Локален текст след конфликт");
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => url === `/api/v1/articles/${activePreparationArticle.id}` && !init?.method).length).toBeGreaterThan(1));
  });

  it("activates the Draft editor, autosaves after 800ms and has no Save button", async () => {
    const user = userEvent.setup();
    let canonical = activeDraftArticle;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) {
        const body = JSON.parse(String(init.body)) as { title: string; body: string; expectedVersion: number };
        canonical = { ...canonical, title: body.title, content: { title: body.title, body: body.body, version: body.expectedVersion + 1 } };
        return dataResponse(canonical);
      }
      return dataResponse(canonical);
    });
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activeDraftArticle.id}`] },
    );
    await user.click(await screen.findByRole("button", { name: "Редактирай" }));
    const body = screen.getByRole("textbox", { name: "Текст на статията" });
    expect(body).toHaveValue(activeDraftArticle.content.body);
    expect(screen.getByRole("textbox", { name: "Заглавие" })).toHaveValue(activeDraftArticle.content.title);
    expect(screen.queryByRole("button", { name: /запази/i })).toBeNull();
    await user.clear(body);
    await user.type(body, "Нова автоматично запазена версия.");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(await screen.findByText("Запазено")).toBeInTheDocument();
    const put = fetchMock.mock.calls.find(([url, init]) => url.endsWith("/content") && init?.method === "PUT");
    expect(JSON.parse(String((put?.[1] as RequestInit).body))).toEqual({ expectedVersion: 3, title: activeDraftArticle.content.title, body: "Нова автоматично запазена версия." });
  });

  it("serializes saves and sends the newest local text with the confirmed version", async () => {
    const user = userEvent.setup();
    let resolveFirst!: (response: Response) => void;
    const firstResponse = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    const bodies: string[] = [];
    let canonical = activeDraftArticle;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) {
        const body = JSON.parse(String(init.body)) as { body: string; expectedVersion: number };
        bodies.push(body.body);
        if (bodies.length === 1) return firstResponse;
        canonical = { ...canonical, content: { ...canonical.content, body: body.body, version: body.expectedVersion + 1 } };
        return dataResponse(canonical);
      }
      return dataResponse(canonical);
    });
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activeDraftArticle.id}`] },
    );
    await user.click(await screen.findByRole("button", { name: "Редактирай" }));
    const editor = screen.getByRole("textbox", { name: "Текст на статията" });
    await user.clear(editor);
    await user.type(editor, "Първи");
    await user.tab();
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(screen.getByText("Запазване…")).toBeInTheDocument();
    await user.clear(editor);
    await user.type(editor, "Най-нов текст");
    await user.tab();
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(bodies).toHaveLength(1);
    canonical = { ...canonical, content: { ...canonical.content, body: "Първи", version: 4 } };
    resolveFirst(dataResponse(canonical));
    await waitFor(() => expect(bodies).toEqual(["Първи", "Най-нов текст"]));
    const secondPut = fetchMock.mock.calls.filter(([url, init]) => url.endsWith("/content") && init?.method === "PUT")[1];
    expect(JSON.parse(String((secondPut?.[1] as RequestInit).body)).expectedVersion).toBe(4);
  });
  it("keeps local text on failure and resolves 409 only by explicit user choice", async () => {
    const user = userEvent.setup();
    let canonical = activeDraftArticle;
    const server = { ...canonical, content: { ...canonical.content, body: "Версия от друга сесия", version: 4 } };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) return errorResponse("ARTICLE_VERSION_CONFLICT", "Конфликт", 409);
      if (url.endsWith(`/articles/${activeDraftArticle.id}`) && !init?.method) return dataResponse(server);
      return dataResponse(canonical);
    });
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activeDraftArticle.id}`] },
    );
    await user.click(await screen.findByRole("button", { name: "Редактирай" }));
    const editor = screen.getByRole("textbox", { name: "Текст на статията" });
    await user.clear(editor);
    await user.type(editor, "Локален текст");
    await user.tab();
    expect(await screen.findByText("Локалните промени са запазени.")).toBeInTheDocument();
    expect(editor).toHaveValue("Локален текст");
    expect(screen.queryByText("Версия от друга сесия")).toBeNull();
    canonical = server;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) {
        const body = JSON.parse(String(init.body));
        canonical = { ...canonical, content: { ...canonical.content, body: body.body, version: body.expectedVersion + 1 } };
        return dataResponse(canonical);
      }
      return dataResponse(canonical);
    });
    await user.click(screen.getByRole("button", { name: "Използвай моите промени" }));
    await waitFor(() => {
      const put = fetchMock.mock.calls.filter(([url, init]) => url.endsWith("/content") && init?.method === "PUT").at(-1);
      expect(JSON.parse(String((put?.[1] as RequestInit).body))).toMatchObject({ expectedVersion: 4, body: "Локален текст" });
    });
  });

  it("continues a failed Preparation manually into the same canonical Draft", async () => {
    const user = userEvent.setup();
    const eligible = {
      ...activePreparationArticle,
      editorialFocus: { ...activePreparationArticle.editorialFocus, confirmedAt: "2026-09-25T11:00:00Z" },
      preparation: { ...activePreparationArticle.preparation!, focusConfirmed: true, draftEligible: true, availableActions: ["CHANGE_FOCUS", "EDIT", "MAKE_DRAFT"] as ArticleDetail["availableActions"] },
      availableActions: ["CHANGE_FOCUS", "EDIT", "MAKE_DRAFT"] as ArticleDetail["availableActions"],
    };
    let canonical: ArticleDetail = eligible;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) {
        const body = JSON.parse(String(init.body)) as { title: string; body: string; expectedVersion: number };
        canonical = { ...activeDraftArticle, id: eligible.id, story: eligible.story, content: { title: body.title, body: body.body, version: body.expectedVersion + 1 }, warnings: [] };
        return dataResponse(canonical);
      }
      return dataResponse(canonical);
    });
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${eligible.id}`] },
    );
    await user.click(await screen.findByRole("button", { name: "Редактирай" }));
    const editor = screen.getByRole("textbox", { name: "Текст на статията" });
    expect(editor).toHaveValue("");
    await user.type(editor, "Ръчен текст след Generation failure.");
    await user.tab();
    expect(await screen.findByRole("heading", { name: "Чернова" })).toBeInTheDocument();
    expect(editor).toHaveValue("Ръчен текст след Generation failure.");
    expect(fetchMock.mock.calls.every(([url, init]) => !(url.endsWith("/draft") && init?.method === "POST"))).toBe(true);
  });






  it("keeps draft content before evidence and opens the evidence disclosure on demand", async () => {
    fetchMock.mockResolvedValue(dataResponse(activeDraftArticle));
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/articles/:articleId" element={<ArticleWorkspace />} />
      </Routes>,
      { initialEntries: [`/articles/${activeDraftArticle.id}`] },
    );
    const title = await screen.findByRole("heading", { level: 1, name: activeDraftArticle.content.title });
    const focus = screen.getByRole("heading", { name: "Редакционен фокус" });
    const draft = screen.getByRole("heading", { name: "Чернова" });
    const disclosure = screen.getByRole("button", { name: "Факти, източници и липсваща информация" });
    expect(title.compareDocumentPosition(focus) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(focus.compareDocumentPosition(draft) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(draft.compareDocumentPosition(disclosure) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(activeDraftArticle.factsAndSources[0]!.text)).not.toBeVisible();
    await user.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(activeDraftArticle.factsAndSources[0]!.text)).toBeVisible();
  });

  it("keeps focus read-only when backend actions do not authorize editing", async () => {
    const readOnly = { ...activePreparationArticle, availableActions: [] };
    fetchMock.mockResolvedValue(dataResponse(readOnly));
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );

    await screen.findByRole("heading", { name: "Редакционен фокус" });
    expect(screen.queryByRole("textbox", { name: "Редакционен фокус" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Избери фокус|Промени фокуса/ })).toBeNull();
  });

  it("renders Article facts and gaps from the read-only detail response", async () => {
    fetchMock.mockResolvedValue(dataResponse(activeDraftArticle));
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/articles/:articleId" element={<ArticleWorkspace />} />
      </Routes>,
      { initialEntries: [`/articles/${activeDraftArticle.id}`] },
    );

    const disclosure = await screen.findByRole("button", { name: "Факти, източници и липсваща информация" });
    await user.click(disclosure);
    expect(screen.getByText(activeDraftArticle.factsAndSources![0]!.text)).toBeVisible();
    expect(screen.getByText(activeDraftArticle.missingInformation!.items[0]!.question)).toBeVisible();
    expect(screen.getByText(activeDraftArticle.missingInformation!.items[0]!.reason!)).toBeVisible();
    expect(fetchMock.mock.calls.every(([, init]) => !("method" in (init ?? {})) || init.method === "GET")).toBe(true);
  });

});

describe("C4 Отбележи като готова", () => {
  const reviewWarning = {
    id: "warn_review_1",
    severity: "review" as const,
    message: "Изречение без директна опора в източниците.",
    affectedText: "Във вътрешния двор се събраха граждани, които питат за съдбата на пазара.",
    blocking: false,
  };
  const blockingWarning = {
    id: "warn_blocking_1",
    severity: "blocking" as const,
    message: "Има непопълнена информация, която пречи да продължите.",
    blocking: true,
  };
  const infoWarning = {
    id: "warn_info_1",
    severity: "info" as const,
    message: "Проверката на твърденията не е завършена изцяло. Прегледайте текста.",
    blocking: false,
  };

  function articleRoute() {
    return (
      <Routes>
        <Route path="/articles/:articleId" element={<ArticleWorkspace />} />
        <Route path="/stories/:storyId" element={<p>История</p>} />
      </Routes>
    );
  }

  it("shows the current warnings before the decision, with the frozen severity hierarchy", async () => {
    const draft = { ...activeDraftArticle, warnings: [blockingWarning, reviewWarning, infoWarning] };
    fetchMock.mockResolvedValue(dataResponse(draft));
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${draft.id}`] });

    await screen.findByRole("heading", { name: "Предупреждения" });
    const review = screen.getByText(reviewWarning.message).closest("li")!;
    expect(review).toHaveTextContent(reviewWarning.affectedText);
    // The blocking note is visually stronger than the informational one.
    const blocking = screen.getByText(blockingWarning.message).closest("li")!;
    const info = screen.getByText(infoWarning.message).closest("li")!;
    expect(blocking.className).not.toBe(info.className);
    expect(blocking.className).toMatch(/warningBlocking/);
    expect(info.className).toMatch(/warningInfo/);
    // Nothing is hidden behind a modal opened only after clicking.
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("marks the article ready from the backend action and shows the canonical Готова", async () => {
    const user = userEvent.setup();
    let canonical = { ...activeDraftArticle, warnings: [reviewWarning] };
    const ready = {
      ...activeReadyArticle,
      id: activeDraftArticle.id,
      story: activeDraftArticle.story,
      content: canonical.content,
      warnings: [reviewWarning],
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/ready")) {
        canonical = ready;
        return dataResponse(ready);
      }
      return dataResponse(canonical);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeDraftArticle.id}`] });

    const action = await screen.findByRole("button", { name: "Отбележи като готова" });
    expect(screen.getByText(reviewWarning.message)).toBeInTheDocument();
    await user.click(action);

    expect(await screen.findByText("Готова")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url, init]) => url.endsWith("/ready") && init?.method === "POST");
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({ expectedVersion: 3 });
    expect(canonical.content.body).toBe(activeDraftArticle.content.body);
  });

  it("offers no readiness action when the backend does not authorize it", async () => {
    const draft = { ...activeDraftArticle, availableActions: ["EDIT"] as ArticleDetail["availableActions"] };
    fetchMock.mockResolvedValue(dataResponse(draft));
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeDraftArticle.id}`] });

    await screen.findByRole("heading", { name: "Чернова" });
    expect(screen.queryByRole("button", { name: "Отбележи като готова" })).toBeNull();
    expect(fetchMock.mock.calls.every(([, init]) => !("method" in (init ?? {})) || init.method === "GET")).toBe(true);
  });

  it("flushes a pending autosave before sending the readiness command", async () => {
    const user = userEvent.setup();
    let canonical = activeDraftArticle;
    const ready = { ...activeReadyArticle, id: activeDraftArticle.id, story: activeDraftArticle.story };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) {
        const body = JSON.parse(String(init.body)) as { body: string; expectedVersion: number };
        canonical = {
          ...canonical,
          content: { ...canonical.content, body: body.body, version: body.expectedVersion + 1 },
          validation: { ...canonical.validation, contentVersion: body.expectedVersion + 1 },
        };
        return dataResponse(canonical);
      }
      if (init?.method === "POST" && url.endsWith("/ready")) return dataResponse(ready);
      return dataResponse(canonical);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeDraftArticle.id}`] });

    await user.click(await screen.findByRole("button", { name: "Редактирай" }));
    const body = screen.getByRole("textbox", { name: "Текст на статията" });
    await user.clear(body);
    await user.type(body, "Нов текст преди готовност.");
    // The autosave is still pending: the readiness command must await it.
    await user.click(screen.getByRole("button", { name: "Отбележи като готова" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url, init]) => url.endsWith("/ready") && init?.method === "POST"),
      ).toBe(true),
    );
    const save = fetchMock.mock.calls.find(([url, init]) => url.endsWith("/content") && init?.method === "PUT");
    const readyCall = fetchMock.mock.calls.find(([url, init]) => url.endsWith("/ready") && init?.method === "POST");
    const saved = JSON.parse(String((save?.[1] as RequestInit).body)) as { expectedVersion: number };
    const marked = JSON.parse(String((readyCall?.[1] as RequestInit).body)) as { expectedVersion: number };
    expect(marked.expectedVersion).toBe(saved.expectedVersion + 1);
    expect(marked.expectedVersion).toBe(4);
  });

  it("keeps the Draft readable, prevents a duplicate click and exposes no internal stage", async () => {
    const user = userEvent.setup();
    let resolveReady!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { resolveReady = resolve; });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/ready")) return pending;
      return dataResponse(activeDraftArticle);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeDraftArticle.id}`] });

    await user.click(await screen.findByRole("button", { name: "Отбележи като готова" }));
    const pendingButton = await screen.findByRole("button", { name: "Проверява се…" });
    expect(pendingButton).toBeDisabled();
    await user.click(pendingButton);
    expect(
      fetchMock.mock.calls.filter(([url, init]) => url.endsWith("/ready") && init?.method === "POST"),
    ).toHaveLength(1);
    expect(screen.getByText(activeDraftArticle.content.body)).toBeInTheDocument();
    for (const stage of ["Проверка на твърдения", "Модел", "аудит", "Ingest"]) {
      expect(screen.queryByText(stage)).toBeNull();
    }
    resolveReady(dataResponse(activeReadyArticle));
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/ready")).length).toBeGreaterThan(0),
    );
  });

  it("keeps the Draft after a blocking refusal and refetches the canonical warnings", async () => {
    const user = userEvent.setup();
    let refused = false;
    const blocked = {
      ...activeDraftArticle,
      warnings: [blockingWarning],
      availableActions: ["EDIT"] as ArticleDetail["availableActions"],
      validation: { ...activeDraftArticle.validation, blocking: true, readyEligible: false },
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/ready") && !refused) {
        refused = true;
        return errorResponse(
          "SAFETY_BLOCKED",
          "Проверката на текущия текст откри пречи. Разгледайте предупрежденията.",
          409,
        );
      }
      return dataResponse(refused ? blocked : activeDraftArticle);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeDraftArticle.id}`] });

    await user.click(await screen.findByRole("button", { name: "Отбележи като готова" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Проверката на текущия текст откри пречи");
    await waitFor(() => expect(screen.getByText(blockingWarning.message)).toBeInTheDocument());
    expect(screen.getAllByText("Чернова").length).toBeGreaterThan(0);
    expect(screen.queryByText("Готова")).toBeNull();
  });

  it("renders Готова as a read-only final review with no finalize and no reopen", async () => {
    fetchMock.mockResolvedValue(dataResponse(activeReadyArticle));
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeReadyArticle.id}`] });

    expect(await screen.findByText("Готова")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Финален преглед" })).toBeInTheDocument();
    expect(screen.getByText(activeReadyArticle.content.body)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: activeReadyArticle.story.title! })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Редакционен фокус" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Факти, източници и липсваща информация" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Финализирай/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Редактирай" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отбележи като готова" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("Archive and Settings", () => {
  it("keeps the archive list read-only", async () => {
    fetchMock.mockResolvedValue(dataResponse({ articles: [finalizedArchiveArticle] }));
    renderWithProviders(<ArchivePage />, { route: "/archive" });
    await screen.findByRole("link", { name: finalizedArchiveArticle.title });
    expect(screen.getByRole("link", { name: finalizedArchiveArticle.title })).toHaveAttribute("href", `/archive/${finalizedArchiveArticle.id}`);
    expect(screen.queryByRole("button", { name: /Редактирай|Финализирай|Направи чернова/ })).toBeNull();
  });

  it("exposes exactly four disabled technical settings", () => {
    renderWithProviders(<SettingsLanding />, { route: "/settings" });
    const entries = screen.getAllByRole("listitem").filter((entry) => entry.getAttribute("aria-disabled") === "true");
    expect(entries).toHaveLength(4);
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining("Източници"), expect.stringContaining("AI и разходи"),
      expect.stringContaining("Канали за вход"), expect.stringContaining("Система"),
    ]);
    entries.forEach((entry) => expect(entry).toHaveAttribute("aria-disabled", "true"));
  });
});
