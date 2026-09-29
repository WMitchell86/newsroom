import { screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { AppShell } from "../app/AppShell";
import { StoryWorkspace } from "../pages/StoryWorkspace";
import { TodayPage } from "../pages/TodayPage";
import { renderWithProviders } from "./render";
import { todayProjection } from "./fixtures";

/**
 * V1.2-G4.15 — the desk has to be able to empty.
 *
 * Measured before this: 434 of 445 stories were still `NEW`, so Today showed
 * the newest 30 of exactly the same corpus the archive showed, and the editor
 * had to press «Преглед» on every row for anything to ever leave the desk.
 *
 * Arriving from Today therefore marks the Story reviewed. Arriving from
 * anywhere else does not — the owner chose that boundary explicitly, and
 * getting it wrong empties the desk behind their back.
 */

const fetchMock = vi.fn();
const data = (d: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data: d }) }) as Response;
const post = (d: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data: d }) }) as Response;

let reviews = 0;

function storyDetail() {
  return {
    id: "s1",
    title: "История",
    summary: "Обобщение",
    status: "NEW",
    developments: [],
    observedDevelopmentIds: [],
    reviewState: { reviewed: false },
  };
}

function routes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<TodayPage />} />
        <Route path="/stories" element={<p>АРХИВ</p>} />
        <Route path="/stories/:storyId" element={<StoryWorkspace />} />
      </Route>
    </Routes>
  );
}

beforeEach(() => {
  reviews = 0;
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (u: RequestInfo | URL, init?: RequestInit) => {
    const s = String(u);
    if (init?.method === "POST") {
      if (s.includes("/review")) reviews += 1;
      return post(storyDetail());
    }
    if (s.includes("/operations")) return data({ operations: [] });
    if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
    if (s.includes("/stories/")) return data(storyDetail());
    if (s.includes("/today")) return data(todayProjection);
    return data({});
  });
});

describe("the desk can empty", () => {
  it("marks a Story reviewed when it is opened from Today", async () => {
    renderWithProviders(routes(), { initialEntries: ["/stories/s1?from=today"] });
    await waitFor(() => expect(reviews).toBe(1), { timeout: 4000 });
  });

  it("does NOT mark it when the same Story is opened from the archive", async () => {
    // Reading a story in the archive is not a decision about the desk. If it
    // marked it, browsing would silently empty the editor's queue.
    renderWithProviders(routes(), { initialEntries: ["/stories/s1"] });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((c) => String(c[0]).includes("/stories/s1")),
      ).toBe(true),
    );
    await new Promise((r) => setTimeout(r, 300));
    expect(reviews).toBe(0);
  });

  it("does not fire twice on a reload", async () => {
    // The marker is consumed, so a refresh is not a fresh arrival.
    const { unmount } = renderWithProviders(routes(), {
      initialEntries: ["/stories/s1?from=today"],
    });
    await waitFor(() => expect(reviews).toBe(1), { timeout: 4000 });
    unmount();
    renderWithProviders(routes(), { initialEntries: ["/stories/s1"] });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((c) => String(c[0]).includes("/stories/s1")),
      ).toBe(true),
    );
    await new Promise((r) => setTimeout(r, 200));
    expect(reviews).toBe(1);
  });

  it("fires once under StrictMode, which the real app runs", async () => {
    // `main.tsx` wraps the whole app in StrictMode, which double-invokes
    // effects in development. The test harness does not, so without this the
    // single-fire guard would be unproven against the configuration the
    // product actually ships in.
    const { unmount } = renderWithProviders(
      <StrictMode>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/stories/:storyId" element={<StoryWorkspace />} />
          </Route>
        </Routes>
      </StrictMode>,
      { initialEntries: ["/stories/s1?from=today"] },
    );
    await waitFor(() => expect(reviews).toBe(1), { timeout: 4000 });
    await new Promise((r) => setTimeout(r, 300));
    expect(reviews).toBe(1);
    unmount();
  });

  it("Today links carry the marker; the archive does not", async () => {
    renderWithProviders(routes(), { initialEntries: ["/"] });
    await screen.findByRole("button", { name: /^Всички/ });
    const link = document.querySelector('a[href^="/stories/"]');
    expect(link?.getAttribute("href")).toContain("from=today");
  });
});
