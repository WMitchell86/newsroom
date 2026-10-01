import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OperationsPage } from "../pages/OperationsPage";
import { renderWithProviders } from "./render";

/**
 * V1.2-G4.36 — the page that answers "what became of what I asked for".
 *
 * Measured on the operator's own desk before this test: two Quick Drafts had
 * run and returned `needs_attention` with no Article to show for either, and
 * `var/operations.json` recorded both as `succeeded` with an empty `error`.
 * Reloading Today then offered «Чернова» again as if nothing had been asked,
 * and this page said «Готово».
 *
 * The refusal travels as the command's own `outcome`, separate from the
 * worker's `status`, because the two are different questions: the worker did
 * return. A page that renders only `status` cannot tell a Draft from a refusal,
 * and it is the only place the editor can look after a reload.
 */

const fetchMock = vi.fn();
const data = (d: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data: d }) }) as Response;

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("OperationsPage", () => {
  it("says a refused operation did not produce anything, and why", async () => {
    fetchMock.mockResolvedValue(
      data({
        operations: [
          {
            operationToken: "op_a973d498e835f5caa9788f2e",
            storyId: "quick-draft:s32aa7fd0b7aaa95",
            status: "succeeded",
            errorCode: "",
            error: "",
            outcome: "needs_attention",
            outcomeCode: "NO_DRAFT_MATERIAL",
            outcomeMessage: "За чернова първо е нужно проучване на историята.",
            kind: "Чернова по история",
            topic: "Ремонтът на улицата започва през октомври",
            topicHref: "/stories/s32aa7fd0b7aaa95",
            startedAt: "2026-09-30T08:12:00+00:00",
            finishedAt: "2026-09-30T08:12:04+00:00",
          },
        ],
      }),
    );

    renderWithProviders(<OperationsPage />);

    await waitFor(() => expect(screen.getByText("Чернова по история")).toBeInTheDocument());
    // The lie this replaces: a green «Готово» over work that produced nothing.
    expect(screen.queryByText("Готово")).toBeNull();
    expect(screen.getByText("Не се получи")).toBeInTheDocument();
    expect(
      screen.getByText("За чернова първо е нужно проучване на историята."),
    ).toBeInTheDocument();
  });

  it("still calls a genuine success a success", async () => {
    fetchMock.mockResolvedValue(
      data({
        operations: [
          {
            operationToken: "op_b35e783607667751d1d07418",
            storyId: "article-draft:art_1a1dd9bb30afd00",
            status: "succeeded",
            errorCode: "",
            error: "",
            outcome: "draft_created",
            kind: "Чернова",
            topic: "Съветът одобри графика за ремонта",
            topicHref: "/articles/art_1a1dd9bb30afd00",
            startedAt: "2026-09-30T09:00:00+00:00",
            finishedAt: "2026-09-30T09:00:12+00:00",
          },
        ],
      }),
    );

    renderWithProviders(<OperationsPage />);

    await waitFor(() => expect(screen.getByText("Готово")).toBeInTheDocument());
    expect(screen.queryByText("Не се получи")).toBeNull();
    expect(screen.getByText("Чернова")).toBeInTheDocument();
  });

  it("names a rewrite and a quick draft instead of calling them «Операция»", async () => {
    fetchMock.mockResolvedValue(
      data({
        operations: [
          {
            operationToken: "op_1",
            storyId: "article-rewrite:art_39f4c97850b537d",
            status: "succeeded",
            errorCode: "",
            error: "",
            outcome: "",
            kind: "Пренапиши",
            topic: "Съветът одобри графика",
            topicHref: "/articles/art_39f4c97850b537d",
            startedAt: "2026-09-30T10:00:00+00:00",
            finishedAt: "2026-09-30T10:00:09+00:00",
          },
          {
            operationToken: "op_2",
            storyId: "quick-draft:s2f114aa900b37a1",
            status: "succeeded",
            errorCode: "",
            error: "",
            outcome: "",
            kind: "Чернова по история",
            topic: "Ремонтът започва през октомври",
            topicHref: "/stories/s2f114aa900b37a1",
            startedAt: "2026-09-30T10:05:00+00:00",
            finishedAt: "2026-09-30T10:05:07+00:00",
          },
        ],
      }),
    );

    renderWithProviders(<OperationsPage />);

    await waitFor(() => expect(screen.getByText("Пренапиши")).toBeInTheDocument());
    expect(screen.getByText("Чернова по история")).toBeInTheDocument();
    expect(screen.queryByText("Операция")).toBeNull();
  });
  it("shows the headline as the link, and when it ran", async () => {
    // V1.2-G4.38. Measured before this: the anchor text WAS the internal id
    // (`art_85e69497b45cdbe`), there was no time anywhere on the page, and the
    // Story-scoped rows had no link at all.
    fetchMock.mockResolvedValue(
      data({
        operations: [
          {
            operationToken: "op_t1",
            storyId: "article-draft:art_1a1dd9bb30afd00",
            status: "succeeded",
            errorCode: "",
            error: "",
            outcome: "",
            kind: "Чернова",
            topic: "Съветът одобри графика за ремонта",
            topicHref: "/articles/art_1a1dd9bb30afd00",
            startedAt: "2026-09-30T09:00:00+00:00",
            finishedAt: "2026-09-30T09:00:12+00:00",
          },
        ],
      }),
    );

    renderWithProviders(<OperationsPage />);

    const link = await screen.findByRole("link", { name: "Съветът одобри графика за ремонта" });
    expect(link).toHaveAttribute("href", "/articles/art_1a1dd9bb30afd00");
    // The id is never what the editor is shown as the subject.
    expect(screen.queryByText("art_1a1dd9bb30afd00")).toBeNull();
    // A time is rendered, and it is not the monotonic registry value.
    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument();
  });

  it("links every scope the server names a subject for", async () => {
    // The property that broke: measured across the six scope shapes the
    // application actually creates, only 2 produced a link.
    fetchMock.mockResolvedValue(
      data({
        operations: [
          { operationToken: "a", storyId: "article-draft:art_x", status: "succeeded",
            errorCode: "", error: "", outcome: "", kind: "Чернова",
            topic: "Чернова за ремонта", topicHref: "/articles/art_x",
            startedAt: "2026-09-30T09:00:00+00:00", finishedAt: "2026-09-30T09:00:01+00:00" },
          { operationToken: "b", storyId: "article-rewrite:art_x", status: "succeeded",
            errorCode: "", error: "", outcome: "", kind: "Пренапиши",
            topic: "Пренаписана чернова", topicHref: "/articles/art_x",
            startedAt: "2026-09-30T09:00:00+00:00", finishedAt: "2026-09-30T09:00:02+00:00" },
          { operationToken: "c", storyId: "quick-draft:s_1", status: "succeeded",
            errorCode: "", error: "", outcome: "", kind: "Чернова по история",
            topic: "Историята за ремонта", topicHref: "/stories/s_1",
            startedAt: "2026-09-30T09:00:00+00:00", finishedAt: "2026-09-30T09:00:03+00:00" },
          { operationToken: "d", storyId: "s_1", status: "succeeded",
            errorCode: "", error: "", outcome: "", kind: "Проучване",
            topic: "Историята за ремонта", topicHref: "/stories/s_1",
            startedAt: "2026-09-30T09:00:00+00:00", finishedAt: "2026-09-30T09:00:04+00:00" },
        ],
      }),
    );

    renderWithProviders(<OperationsPage />);

    await screen.findByText("Пренапиши");
    // All four subjects are reachable, and the two Story-scoped ones — the
    // rows that previously had nowhere to go — point at the Story page.
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toHaveLength(4);
    expect(hrefs.filter((href) => href === "/stories/s_1")).toHaveLength(2);
    expect(hrefs.every((href) => href?.startsWith("/articles/") || href === "/stories/s_1")).toBe(true);
  });

  it("shows a running operation's start time and never invents a finish", async () => {
    fetchMock.mockResolvedValue(
      data({
        operations: [
          { operationToken: "r1", storyId: "quick-draft:s_1", status: "running",
            errorCode: "", error: "", outcome: "", kind: "Чернова по история",
            topic: "Историята за ремонта", topicHref: "/stories/s_1",
            startedAt: "2026-09-30T09:00:00+00:00", finishedAt: "" },
        ],
      }),
    );

    renderWithProviders(<OperationsPage />);

    await screen.findByText("В момента върви");
    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument();
  });

  it("says so plainly when the server recorded no time at all", async () => {
    fetchMock.mockResolvedValue(
      data({
        operations: [
          { operationToken: "n1", storyId: "today-refresh", status: "succeeded",
            errorCode: "", error: "", outcome: "", kind: "Обновяване на новините",
            topic: "", topicHref: "", startedAt: "", finishedAt: "" },
        ],
      }),
    );

    renderWithProviders(<OperationsPage />);

    await screen.findByText("Обновяване на новините");
    // Not a dash: an unstamped row is a different fact from an old one.
    expect(screen.getByText("няма дата")).toBeInTheDocument();
    expect(screen.queryByText("Операция")).toBeNull();
  });
});
