import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../app/AppShell";
import { TodayPage } from "../pages/TodayPage";
import { renderWithProviders } from "./render";
import { todayProjection } from "./fixtures";

/**
 * V1.2-G4.11 — moving between pages must not throw away what the editor chose.
 *
 * The complaint: press Draft, go to Today, go to Articles, come back — the
 * tab, scope, sort and search term were gone. The cause was structural: Today
 * held all four in `useState`, so unmounting reset them, while the Stories
 * page (already URL-backed) kept its state. One product, two different
 * memories, and the editor was on the losing side of it.
 */

const fetchMock = vi.fn();
const data = (d: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data: d }) }) as Response;

function routes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<TodayPage />} />
        <Route path="/stories" element={<p>РАЗДЕЛ ИСТОРИИ</p>} />
        <Route path="/articles" element={<p>РАЗДЕЛ СТАТИИ</p>} />
        <Route path="/articles/:articleId" element={<p>СТАТИЯ</p>} />
        <Route path="/operations" element={<p>ЛОГ</p>} />
      </Route>
    </Routes>
  );
}

beforeEach(() => {
  // The remembered Today view lives in sessionStorage by design, so it leaks
  // between tests unless cleared. A test that inherits another test's desk is
  // not testing this one, and it fails only in a full run, which is the worst
  // possible moment to discover that.
  window.sessionStorage.clear();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
    const s = String(u);
    if (s.includes("/today")) return data(todayProjection);
    if (s.includes("/operations")) return data({ operations: [] });
    if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
    return data({});
  });
});

describe("state survives navigation", () => {
  it("keeps the chosen tab, scope and sort when the editor leaves and returns", async () => {
    const user = userEvent.setup();
    renderWithProviders(routes(), { initialEntries: ["/"] });

    await screen.findByRole("button", { name: /^Нови/ });
    await user.click(screen.getByRole("button", { name: /^Нови/ }));
    await user.selectOptions(screen.getByLabelText(/Сортирай/), "publishers");

    // Leave for two other destinations and come back.
    await user.click(screen.getByRole("link", { name: "Истории" }));
    await screen.findByText("РАЗДЕЛ ИСТОРИИ");
    await user.click(screen.getByRole("link", { name: "Статии" }));
    await screen.findByText("РАЗДЕЛ СТАТИИ");
    await user.click(screen.getByRole("link", { name: "Днес" }));

    // The desk must come back exactly as it was left. `findBy*` rather than
    // `waitFor(getBy*)`: the earlier version could observe a button mid-render,
    // before its label was attached, and fail intermittently in a full run.
    const restored = await screen.findByRole("button", { name: /^Нови/ });
    expect(restored).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText(/Сортирай/)).toHaveValue("publishers");
  });

  it("reflects the view in the URL, so a link and Back both work", async () => {
    const user = userEvent.setup();
    renderWithProviders(routes(), { initialEntries: ["/"] });
    await screen.findByRole("button", { name: /^В развитие/ });
    await user.click(screen.getByRole("button", { name: /^В развитие/ }));
    // A view that lives only in memory cannot be linked to or shared.
    // The control itself is the proof: the view came from the URL, not from a
    // click. A MemoryRouter does not touch window.location, so asserting on
    // window.location.search here would be asserting on the test harness.
    expect(screen.getByRole("button", { name: /^В развитие/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("opens straight into a linked view without clicking anything", async () => {
    renderWithProviders(routes(), { initialEntries: ["/?tab=new&scope=all"] });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Нови/ })).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("falls back to the documented default for an unknown parameter", async () => {
    // A hand-edited link must not leave the desk in a state the controls
    // cannot show and the editor cannot get out of.
    renderWithProviders(routes(), { initialEntries: ["/?tab=invented"] });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Всички/ })).toHaveAttribute("aria-pressed", "true"),
    );
  });
});

describe("running work is visible from any page", () => {
  it("shows a strip while an operation is in flight, and links to the log", async () => {
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations"))
        return data({
          operations: [
            { operationToken: "op_1", storyId: "article-draft:art_7ec", status: "running",
              errorCode: "", error: "" },
          ],
        });
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/stories"] });
    const strip = await screen.findByRole("status");
    expect(strip).toHaveTextContent("В момента върви");
    expect(screen.getByRole("link", { name: "Подробности" })).toHaveAttribute(
      "href",
      "/operations",
    );
  });

  it("shows nothing when there is no unfinished work", async () => {
    // A permanent "0 running" badge teaches the eye to skip the one place
    // status is shown.
    renderWithProviders(routes(), { initialEntries: ["/"] });
    await screen.findByRole("button", { name: /^Всички/ });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("does not treat a finished operation as running", async () => {
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations"))
        return data({
          operations: [
            { operationToken: "op_1", storyId: "s1", status: "succeeded", errorCode: "", error: "" },
            { operationToken: "op_2", storyId: "s2", status: "failed", errorCode: "X", error: "y" },
          ],
        });
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/"] });
    await screen.findByRole("button", { name: /^Всички/ });
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("the status line cannot break the product", () => {
  it("renders the desk even when the operations payload is an unexpected shape", async () => {
    // This strip sits in the SHELL, above every page. A status line that can
    // unmount the editor's desk is worse than no status line: the first
    // version called `.filter` on a `{}` and took the whole tree with it.
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations")) return data({ operations: null });
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/"] });
    // The desk is still there. That is the whole assertion.
    await screen.findByRole("button", { name: /^Всички/ });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("survives a failed operations request", async () => {
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations")) throw new Error("network down");
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/"] });
    await screen.findByRole("button", { name: /^Всички/ });
  });
});

/**
 * V1.2-G4.12 — "tell me when it is ready", from wherever the editor is.
 *
 * The strip from G4.11 answers "is anything happening". The question an editor
 * actually has after pressing a button and walking away is "is it done", and
 * the only way to learn it was to go back and look.
 */
describe("ready notice", () => {
  function op(status: string, storyId = "article-draft:art_7ecf") {
    return { operationToken: "op_1", storyId, status, errorCode: "", error: "" };
  }

  it("announces a draft that finished while the editor was on another page", async () => {
    let phase = 0;
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations")) return data({ operations: [op(phase ? "succeeded" : "running")] });
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/stories"] });
    // While it runs, the strip says so and there is nothing to announce yet.
    expect(await screen.findByText(/В момента върви/)).toBeInTheDocument();
    expect(screen.queryByText("Черновата е готова")).toBeNull();

    phase = 1;
    await waitFor(() => expect(screen.getByText("Черновата е готова")).toBeInTheDocument(), {
      timeout: 6000,
    });
    // And it takes the editor straight to the finished work.
    expect(screen.getByRole("link", { name: "Черновата е готова" })).toHaveAttribute(
      "href",
      "/articles/art_7ecf",
    );
  }, 12_000);

  it("does not announce work that was already finished before the page opened", async () => {
    // A page that greets you with yesterday's finished drafts is a backlog,
    // not a notification. The Articles list is the backlog.
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations")) return data({ operations: [op("succeeded")] });
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/stories"] });
    await screen.findByText("РАЗДЕЛ ИСТОРИИ");
    expect(screen.queryByText("Черновата е готова")).toBeNull();
  }, 12_000);

  it("does not shout about a draft on the page the editor is already reading", async () => {
    let phase = 0;
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations")) return data({ operations: [op(phase ? "succeeded" : "running")] });
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/articles/art_7ecf"] });
    await screen.findByText(/В момента върви/);
    phase = 1;
    // The Article page shows its own state; announcing it there is noise.
    await new Promise((r) => setTimeout(r, 400));
    expect(screen.queryByText("Черновата е готова")).toBeNull();
  }, 12_000);

  it("announces a finished refresh, which belongs to no single page", async () => {
    let phase = 0;
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations"))
        return data({ operations: [op(phase ? "succeeded" : "running", "today-refresh")] });
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/stories"] });
    await screen.findByText(/В момента върви/);
    phase = 1;
    await waitFor(() => expect(screen.getByText("Новините са обновени")).toBeInTheDocument(), {
      timeout: 6000,
    });
  }, 12_000);

  it("can be dismissed and does not come back on the next poll", async () => {
    let phase = 0;
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const s = String(u);
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations")) return data({ operations: [op(phase ? "succeeded" : "running")] });
      if (s.includes("/health")) return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    });
    renderWithProviders(routes(), { initialEntries: ["/stories"] });
    await screen.findByText(/В момента върви/);
    phase = 1;
    // The poll is every 3s, so the default 1s findBy timeout is not enough.
    await waitFor(() => expect(screen.getByText("Черновата е готова")).toBeInTheDocument(), {
      timeout: 6000,
    });
    await user.click(screen.getByRole("button", { name: /Скрий/ }));
    expect(screen.queryByText("Черновата е готова")).toBeNull();
  }, 12_000);
});
