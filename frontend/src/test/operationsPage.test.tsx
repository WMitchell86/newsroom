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
          },
          {
            operationToken: "op_2",
            storyId: "quick-draft:s2f114aa900b37a1",
            status: "succeeded",
            errorCode: "",
            error: "",
            outcome: "",
          },
        ],
      }),
    );

    renderWithProviders(<OperationsPage />);

    await waitFor(() => expect(screen.getByText("Пренапиши")).toBeInTheDocument());
    expect(screen.getByText("Чернова по история")).toBeInTheDocument();
    expect(screen.queryByText("Операция")).toBeNull();
  });
});
