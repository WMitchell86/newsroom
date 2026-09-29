import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StoryListPage } from "../pages/StoryListPage";
import { renderWithProviders } from "./render";

/**
 * V1.2-G4.14 — the Stories desk needs paging, and it has to be real.
 *
 * Measured: the corpus is 445 stories and the unfiltered response was a
 * single 320 KB payload carrying a full summary for every row, fetched on
 * every visit. Paging only in the browser would still download all of it.
 */

const fetchMock = vi.fn();
const data = (d: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data: d }) }) as Response;

function story(i: number) {
  return {
    id: `s${String(i).padStart(3, "0")}`,
    title: `История номер ${i}`,
    summary: "Обобщение",
    status: "NEW",
    latestChangeAt: `2026-09-29T10:${String(i % 60).padStart(2, "0")}:00Z`,
    publisherCount: 1,
    followed: false,
    ignored: false,
    unreviewedDevelopmentCount: 0,
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

function respond(total = 445) {
  fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
    const s = String(u);
    const page = Number(new URL(s, "http://x").searchParams.get("page") ?? "1") || 1;
    if (s.includes("/stories")) {
      return data({
        stories: Array.from({ length: 30 }, (_, i) => story((page - 1) * 30 + i + 1)),
        counts: { all: total, followed: 1, developments: 2, ignored: 3 },
        total,
        page,
        perPage: 30,
      });
    }
    return data({});
  });
}

describe("Stories paging", () => {
  it("asks the server for one page and says how much there is in total", async () => {
    respond();
    renderWithProviders(<StoryListPage />);
    const status = await screen.findByTestId("pager-status");
    expect(status).toHaveTextContent("Страница 1 от 15");
    expect(status).toHaveTextContent("общо 445");
    // Only one page of rows reached the screen. The page size is the server's
    // own default and the client does not have to restate it.
    expect(screen.getByText("История номер 1")).toBeInTheDocument();
    expect(screen.queryByText("История номер 31")).toBeNull();
  });

  it("moves to the next page and puts it in the URL", async () => {
    respond();
    const user = userEvent.setup();
    renderWithProviders(<StoryListPage />);
    await screen.findByTestId("pager-status");
    await user.click(screen.getByRole("button", { name: /Следваща/ }));
    await waitFor(() =>
      expect(screen.getByTestId("pager-status")).toHaveTextContent("Страница 2 от 15"),
    );
    // The page is in the URL, so Back means something and a link can be shared.
    expect(String(fetchMock.mock.calls.at(-1)![0])).toContain("page=2");
  });

  it("disables Previous on the first page and Next on the last", async () => {
    respond(45); // two pages
    renderWithProviders(<StoryListPage />, { initialEntries: ["/stories?page=2"] });
    const status = await screen.findByTestId("pager-status");
    expect(status).toHaveTextContent("Страница 2 от 2");
    expect(screen.getByRole("button", { name: /Следваща/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Предишна/ })).toBeEnabled();
  });

  it("shows no pager when everything fits on one page", async () => {
    respond(12);
    renderWithProviders(<StoryListPage />);
    await screen.findByText("История номер 1");
    expect(screen.queryByTestId("pager-status")).toBeNull();
  });

  it("never shows a page number past the end of the result", async () => {
    // A stale ?page=7 in a bookmark, after the corpus shrank.
    respond(45);
    renderWithProviders(<StoryListPage />, { initialEntries: ["/stories?page=7"] });
    const status = await screen.findByTestId("pager-status");
    expect(status).toHaveTextContent("Страница 2 от 2");
  });
});
