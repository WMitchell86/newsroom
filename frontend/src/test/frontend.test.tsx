import { screen, waitFor, within } from "@testing-library/react";
import { queryKeys, todayOptions } from "../api/queries";
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

import type { StoryDetail } from "../api/dto";
function errorResponse(code: string, message: string, status: number) {
  return {
    ok: false,
    status,
    json: async () => ({ error: { code, message, retryable: false, fieldErrors: [] } }),
  } as Response;
}

function storyRoute() {
  return (
    <Routes>
      <Route path="/stories/:storyId" element={<StoryWorkspace />} />
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
    expect(screen.getByText(activeDraftArticle.factsAndSources![0]!.text)).not.toBeVisible();
    await user.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(activeDraftArticle.factsAndSources![0]!.text)).toBeVisible();
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
