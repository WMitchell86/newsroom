/**
 * V1.2-G4.3 §G — the controlled learning loop, on the editor's own Settings.
 *
 * Product proofs, not snapshots. They assert what the editor can do and, just
 * as importantly, what the screen refuses to do:
 *
 *   - no decision is offered below the threshold;
 *   - a conflict is shown as a question, never with buttons;
 *   - a decision sends only a `patternId` and a flag — never an instruction —
 *     and the canonical state is refetched afterwards.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FeedbackProposal, FeedbackStatus } from "../api/dto";
import { FeedbackSettingsPage } from "../pages/FeedbackSettingsPage";
import { renderWithProviders } from "./render";

const fetchMock = vi.fn();

function dataResponse(data: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => ({ data }) } as Response;
}

function errorResponse(message: string, status = 400) {
  return {
    ok: false,
    status,
    json: async () => ({
      error: { code: "VALIDATION_ERROR", message, retryable: false, fieldErrors: [] },
    }),
  } as Response;
}

function proposal(overrides: Partial<FeedbackProposal> = {}): FeedbackProposal {
  return {
    patternId: "direct_lead",
    label: "по-директно начало",
    target: "GENERAL_DRAFT_INSTRUCTION",
    support: 20,
    total: 20,
    examples: ["Започни директно с факта."],
    suggestedInstruction: "Lead-ът по правило започва с конкретния нов факт.",
    status: "proposed",
    ...overrides,
  };
}

function status(overrides: Partial<FeedbackStatus> = {}): FeedbackStatus {
  return {
    pending: 20,
    threshold: 20,
    eligible: true,
    proposals: [proposal()],
    instructions: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

describe("the learning loop below the threshold", () => {
  it("reports how much feedback exists and offers no decision", async () => {
    fetchMock.mockImplementation(async () =>
      dataResponse(
        status({ pending: 4, eligible: false, proposals: [], instructions: [] }),
      ),
    );
    renderWithProviders(<FeedbackSettingsPage />);

    expect(await screen.findByText("4 от 20 необходими записа.")).toBeInTheDocument();
    expect(screen.getByText(/Анализът се задейства/)).toBeInTheDocument();
    // No proposal means no decision control anywhere on the screen.
    expect(screen.queryByRole("button", { name: "Одобри" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отхвърли" })).toBeNull();
  });
});

describe("the analyzer's proposals", () => {
  it("shows the pattern, its support and the editor comments behind it", async () => {
    fetchMock.mockImplementation(async () => dataResponse(status()));
    renderWithProviders(<FeedbackSettingsPage />);

    expect(await screen.findByText("по-директно начало")).toBeInTheDocument();
    expect(screen.getByText("Подкрепа: 20 от 20")).toBeInTheDocument();
    expect(
      screen.getByText("Lead-ът по правило започва с конкретния нов факт."),
    ).toBeInTheDocument();
    expect(screen.getByText("„Започни директно с факта.“")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Одобри" })).toBeInTheDocument();
  });

  it("shows a conflict as a question, with no decision buttons", async () => {
    fetchMock.mockImplementation(async () =>
      dataResponse(
        status({
          proposals: [
            proposal({
              patternId: "conflicting_length",
              label: "противоречие за дължината",
              status: "conflict",
              support: 0,
              examples: [],
              suggestedInstruction: "Редакторът трябва да избере кое е приоритет.",
            }),
          ],
        }),
      ),
    );
    renderWithProviders(<FeedbackSettingsPage />);

    expect(await screen.findByText("противоречие за дължината")).toBeInTheDocument();
    expect(screen.getByText(/Това е въпрос/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Одобри" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отхвърли" })).toBeNull();
  });
});

describe("a decision", () => {
  it("sends only the pattern id and a flag, then reads the canonical state back", async () => {
    const user = userEvent.setup();
    let decided = false;
    fetchMock.mockImplementation(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);
      if (target.includes("/settings/feedback/decisions")) {
        decided = true;
        const body = JSON.parse(String(init?.body ?? "{}"));
        // The client must never send the instruction text — the server decides
        // the pattern it actually found.
        expect(body).toEqual({ patternId: "direct_lead", approved: true });
        return dataResponse({
          decision: {
            patternId: "direct_lead",
            target: "GENERAL_DRAFT_INSTRUCTION",
            instruction: "Lead-ът по правило започва с конкретния нов факт.",
            support: 20,
            approved: true,
            decidedAt: "2026-10-01T06:00:00Z",
          },
          ...status({
            proposals: [],
            instructions: [
              {
                patternId: "direct_lead",
                target: "GENERAL_DRAFT_INSTRUCTION",
                instruction: "Lead-ът по правило започва с конкретния нов факт.",
                support: 20,
                approved: true,
                decidedAt: "2026-10-01T06:00:00Z",
              },
            ],
          }),
        });
      }
      if (target.includes("/settings/feedback")) {
        return dataResponse(
          decided
            ? status({
                proposals: [],
                instructions: [
                  {
                    patternId: "direct_lead",
                    target: "GENERAL_DRAFT_INSTRUCTION",
                    instruction: "Lead-ът по правило започва с конкретния нов факт.",
                    support: 20,
                    approved: true,
                    decidedAt: "2026-10-01T06:00:00Z",
                  },
                ],
              })
            : status(),
        );
      }
      return dataResponse({});
    });
    renderWithProviders(<FeedbackSettingsPage />);

    await user.click(await screen.findByRole("button", { name: "Одобри" }));

    // The canonical read is refetched, and the rule now shows as active.
    await waitFor(() => expect(screen.getByText(/Активно/)).toBeInTheDocument());
    expect(screen.getByText("Lead-ът по правило започва с конкретния нов факт.")).toBeInTheDocument();
  });

  it("shows a refused decision as the editor's own sentence", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (url: RequestInfo | URL) => {
      const target = String(url);
      if (target.includes("/settings/feedback/decisions")) {
        return errorResponse("Още няма достатъчно записи за това решение.");
      }
      return dataResponse(status());
    });
    renderWithProviders(<FeedbackSettingsPage />);

    await user.click(await screen.findByRole("button", { name: "Одобри" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Още няма достатъчно записи за това решение.")).toBeInTheDocument();
  });
});
