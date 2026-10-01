import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelsSettingsPage } from "../pages/ModelsSettingsPage";
import { renderWithProviders } from "./render";

/**
 * V1.2-G4.39 — `Настройки → AI и модели`, the paid-model switch.
 *
 * This is a SPEND switch, so the tests are mostly negative. They pin the three
 * things that would make it dangerous:
 *
 *   - the consequence is visible BEFORE the decision (the routes it unlocks);
 *   - the screen shows the SERVER's stored state, never the click's optimism;
 *   - a missing provider key is stated, because "on" would otherwise be a lie.
 */

const fetchMock = vi.fn();
const data = (d: unknown, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, json: async () => ({ data: d }) }) as Response;

const SETTINGS = {
  paidEnabled: false,
  softPaidBudgetUsdDay: 2,
  paidCostTodayUsd: 0,
  paidSoftExceeded: false,
  privacyGateEnabled: false,
  day: "2026-10-01",
  keys: { gemini: true, openrouter: true },
  roles: [
    { role: "draft", eligible: 2, total: 7, onExhausted: "fail_visible" },
    { role: "angle", eligible: 0, total: 5, onExhausted: "degraded" },
  ],
  paidRoutes: [
    { role: "draft", provider: "openrouter", model: "openai/gpt-5.6-luna" },
    { role: "angle", provider: "openrouter", model: "openai/gpt-5.6-luna-pro" },
  ],
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

function renderPage() {
  renderWithProviders(<ModelsSettingsPage />);
}

describe("AI и модели — the paid switch", () => {
  it("shows the stored state and what turning it on would unlock", async () => {
    fetchMock.mockResolvedValue(data(SETTINGS));
    renderPage();

    await waitFor(() => expect(screen.getByLabelText(/Разреши платени модели/)).toBeInTheDocument());
    expect(screen.getByText("Забранени")).toBeInTheDocument();
    // The consequence is named, not implied.
    expect(screen.getByText("openrouter:openai/gpt-5.6-luna")).toBeInTheDocument();
    expect(screen.getByText("openrouter:openai/gpt-5.6-luna-pro")).toBeInTheDocument();
    expect(screen.getAllByText("заключен")).toHaveLength(2);
  });

  it("turns paid models on and reports what the SERVER stored", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/settings/models") && init?.method === "PUT") {
        return data({ ...SETTINGS, paidEnabled: true });
      }
      return data(SETTINGS);
    });
    renderPage();

    const toggle = await screen.findByLabelText(/Разреши платени модели/);
    await userEvent.click(toggle);

    await waitFor(() => expect(screen.getByText("Разрешени")).toBeInTheDocument());
    const put = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit)?.method === "PUT",
    );
    expect(JSON.parse(String((put?.[1] as RequestInit).body))).toEqual({ paidEnabled: true });
    // The routes are no longer labelled locked, because the screen now believes
    // the server, not the click.
    expect(screen.queryByText("заключен")).toBeNull();
  });

  it("keeps the switch OFF when the server refuses the write", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/settings/models") && init?.method === "PUT") {
        return {
          ok: false,
          status: 400,
          json: async () => ({
            error: { code: "VALIDATION_ERROR", message: "невалидно", retryable: false },
          }),
        } as Response;
      }
      return data(SETTINGS);
    });
    renderPage();

    await userEvent.click(await screen.findByLabelText(/Разреши платени модели/));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    // The refusal is shown AND the switch did not quietly become "on".
    expect(screen.getByText("Забранени")).toBeInTheDocument();
  });

  it("says plainly that a missing provider key makes the switch useless", async () => {
    fetchMock.mockResolvedValue(data({ ...SETTINGS, keys: { gemini: true, openrouter: false } }));
    renderPage();

    await waitFor(() => expect(screen.getByText(/OPENROUTER_API_KEY/)).toBeInTheDocument());
    // And it does NOT claim paid models are already on.
    expect(screen.getByText("Забранени")).toBeInTheDocument();
  });

  it("flags a role with no usable route instead of hiding it", async () => {
    fetchMock.mockResolvedValue(data(SETTINGS));
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Роля без достъпен маршрут/)).toBeInTheDocument(),
    );
    // angle is 0/5 in the fixture; the table must show that, not round it up.
    // Scoped to the table because `Ъгъл` also names the role in the routes list.
    const table = within(screen.getByRole("table"));
    const dead = table.getByText("Ъгъл").closest("tr");
    expect(dead?.getAttribute("data-dead")).toBe("true");
    expect(dead?.textContent).toContain("0");
  });
  it("refuses an unusable budget out loud instead of doing nothing", async () => {
    // V1.2-G4.41. The button used to `return` silently, so typing "abc" and
    // pressing it looked exactly like a successful save — on the one field that
    // decides how much real money the newsroom may spend.
    const puts: unknown[] = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/settings/models") && init?.method === "PUT") {
        puts.push(JSON.parse(String(init.body)));
        return data({ ...SETTINGS });
      }
      return data(SETTINGS);
    });
    renderPage();

    const field = (await screen.findByLabelText(/Нов софт бюджет/)) as HTMLInputElement;
    const save = screen.getByRole("button", { name: "Запази бюджета" });

    // `type="number"` refuses letters, so the reachable bad values are an empty
    // field, a negative one, and one past the bound — not "abc".
    await userEvent.clear(field);
    expect(screen.getByText("Въведи число.")).toBeInTheDocument();
    expect(save).toBeDisabled();

    await userEvent.type(field, "-5");
    expect(screen.getByText("Бюджетът не може да е отрицателен.")).toBeInTheDocument();
    expect(save).toBeDisabled();
    expect(field).toHaveAttribute("aria-invalid", "true");

    await userEvent.clear(field);
    await userEvent.type(field, "999");
    expect(screen.getByText(/над 500 USD/)).toBeInTheDocument();
    expect(save).toBeDisabled();

    // Nothing was sent while the value was unusable.
    expect(puts).toEqual([]);

    // A real number saves it.
    await userEvent.clear(field);
    await userEvent.type(field, "4.5");
    expect(screen.queryByText("Бюджетът трябва да е число.")).toBeNull();
    await userEvent.click(save);
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({ paidEnabled: false, softPaidBudgetUsdDay: 4.5 });
  });
});
