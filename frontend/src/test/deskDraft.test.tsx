import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../app/AppShell";
import { TodayPage } from "../pages/TodayPage";
import { renderWithProviders } from "./render";
import { todayProjection } from "./fixtures";

/**
 * V1.2-G4.40 — the desk press.
 *
 * Before this the Quick Draft pipeline had exactly one entry point: one click on
 * one Today row. A desk of collected Stories therefore produced drafts only as
 * fast as an editor could press, and when the command refused there was nothing
 * to show for it. The owner asked twice in one evening and got two successes and
 * no Article.
 *
 * This pins the three things the control must do, and each of them has already
 * been wrong in this codebase at least once:
 *
 *   * the press reaches `/today/quick-drafts` with an Idempotency-Key, because a
 *     double click must not draft the same Stories twice;
 *   * the caption is the SERVER's report - the client does not count Stories,
 *     decide eligibility, or summarise a run it did not observe;
 *   * clicking is what triggers it. Nothing runs on render.
 */

const fetchMock = vi.fn();
const data = (d: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data: d }) }) as Response;
const accepted = (d: unknown) =>
  ({ ok: true, status: 202, json: async () => ({ data: d }) }) as Response;

const REPORT = {
  status: "desk_run",
  attempted: 2,
  created: 1,
  limit: 3,
  stories: [
    { storyId: "story-sunche-vo", status: "draft_created", articleId: "art_1" },
    {
      storyId: "story-pomorie",
      status: "needs_attention",
      reasonCode: "NO_DRAFT_MATERIAL",
      message: "Няма от какво да се напише чернова.",
    },
  ],
};

let draftCalls: Array<{ url: string; key: string }> = [];

function routes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<TodayPage />} />
        <Route path="/operations" element={<p>ЛОГ</p>} />
      </Route>
    </Routes>
  );
}

beforeEach(() => {
  draftCalls = [];
  window.sessionStorage.clear();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  fetchMock.mockImplementation(
    async (u: RequestInfo | URL, init?: RequestInit) => {
      const s = String(u);
      if (s.includes("/today/quick-drafts")) {
        draftCalls.push({
          url: s,
          key: String((init?.headers as Record<string, string>)?.["Idempotency-Key"] ?? ""),
        });
        return accepted({ operationToken: "op_" + "a".repeat(24), status: "pending" });
      }
      if (s.includes("/operations/op_")) {
        return data({
          operationToken: "op_" + "a".repeat(24),
          status: "succeeded",
          result: REPORT,
        });
      }
      if (s.includes("/today")) return data(todayProjection);
      if (s.includes("/operations")) return data({ operations: [] });
      if (s.includes("/health"))
        return data({ ok: true, roles: [], unroutableRoles: [], remedy: "" });
      return data({});
    },
  );
});

describe("the desk press", () => {
  it("does not run anything on render", async () => {
    renderWithProviders(routes(), { initialEntries: ["/"] });
    await screen.findByRole("button", { name: "Направи чернови" });
    expect(draftCalls).toHaveLength(0);
  });

  it("sends one keyed press and reports the server's own numbers", async () => {
    const user = userEvent.setup();
    renderWithProviders(routes(), { initialEntries: ["/"] });

    await user.click(await screen.findByRole("button", { name: "Направи чернови" }));

    // The server's report, rendered verbatim. "Готови 1 от 2 (до 3)" is what the
    // run actually did; the client never states a total it did not receive.
    await screen.findByText(/Готови 1 от 2/);
    expect(screen.getByText(/до\s*3/)).toBeTruthy();

    expect(draftCalls).toHaveLength(1);
    const [press] = draftCalls;
    expect(press?.url).toContain("/api/v1/today/quick-drafts");
    expect(press?.url).toContain("scope=region");
    expect(press?.key, "a press without a key could draft the desk twice").toBeTruthy();
  });

  it("surfaces a Story that refused, so a partial run is not a success", async () => {
    const user = userEvent.setup();
    renderWithProviders(routes(), { initialEntries: ["/"] });
    await user.click(await screen.findByRole("button", { name: "Направи чернови" }));

    // 1 of 2 is the honest summary: the run finished, and the editor can see
    // there was real work left over rather than reading "Готово" over one Draft.
    await waitFor(() => expect(screen.getByText(/Готови 1 от 2/)).toBeTruthy());
    expect(screen.queryByText(/Готови 2 от 2/)).toBeNull();
  });
});
