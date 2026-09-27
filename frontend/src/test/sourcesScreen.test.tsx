/**
 * V1.2-G4: the Sources screen, as the editor actually uses it.
 *
 * These are product proofs, not snapshot tests. They assert what the editor can
 * do and — just as importantly — what the screen refuses to do:
 *
 *   §5   one dense list, six columns, in editor language
 *   §6   the authority toggle carries its own explanation
 *   §8   disable goes through the API and comes back from the server
 *   §9   `+ Добави източник` asks for six fields and nothing else
 *   §14  search and the three trivial filters work off the DTO
 *   §21  turning authority ON asks once; turning it OFF never does
 *   §20  a refusal is shown as the editor's own sentence
 *   §22  the screen contains no AI trust score and no publishing vocabulary
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SourceRow, SourcesProjection } from "../api/dto";
import { SourcesPage } from "../pages/SourcesPage";
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

function source(overrides: Partial<SourceRow> = {}): SourceRow {
  return {
    id: "burgas-municipality",
    name: "Община Бургас",
    kind: "official",
    kindLabel: "Официален",
    domain: "burgas.bg",
    address: "Община Бургас",
    monitored: true,
    muteUntil: "",
    factualAuthority: true,
    priority: "high",
    priorityLabel: "Висок",
    note: "",
    health: { status: "unknown", label: "", lastSuccessAt: "" },
    ...overrides,
  };
}

function projection(rows: SourceRow[]): SourcesProjection {
  return {
    sources: rows,
    summary: {
      total: rows.length,
      monitored: rows.filter((row) => row.monitored).length,
      notMonitored: rows.filter((row) => !row.monitored).length,
      factualAuthority: rows.filter((row) => row.factualAuthority).length,
      problems: rows.filter((row) => row.health.status === "problem").length,
    },
  };
}

/** The registry as the shipped install actually looks like, in miniature. */
const REGISTRY = projection([
  source(),
  source({
    id: "bnr-burgas",
    name: "БНР Бургас",
    kind: "media",
    kindLabel: "Медия",
    domain: "bnr.bg",
    address: "БНР Бургас",
    factualAuthority: false,
  }),
  source({
    id: "burgas-library",
    name: "Регионална библиотека „Пейо Яворов“",
    kind: "regional",
    kindLabel: "Регионална медия",
    domain: "",
    address: "Регионална библиотека Бургас",
    monitored: false,
    factualAuthority: false,
    priority: "low",
    priorityLabel: "Нисък",
  }),
]);

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(dataResponse(REGISTRY));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  return renderWithProviders(<SourcesPage />, { route: "/settings/sources" });
}

/**
 * The table row for one source.
 *
 * Scoped by row rather than by document: several rows legitimately share a
 * domain (`burgas.bg` is claimed by three registry rows, §19), so a global text
 * query would not identify which one an action belongs to.
 */
function rowFor(name: string): HTMLElement {
  const row = screen.getAllByRole("row").find((candidate) =>
    within(candidate).queryAllByText(name).length > 0,
  );
  if (!row) throw new Error(`no source row for ${name}`);
  return row;
}

/** The body of the single write request the test made, parsed. */
function lastWriteBody(method: string): unknown {
  const call = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === method);
  return JSON.parse(String((call?.[1] as RequestInit).body));
}

function writeCount(method: string): number {
  return fetchMock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === method).length;
}

describe("Sources screen", () => {
  it("lists the registry in editor language, one row per source", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Източници" })).toBeInTheDocument();
    expect(screen.getByText(/Източниците определят какво следим/)).toBeInTheDocument();

    // The list is a query result, so wait for a row before scoping to one.
    const row = await waitFor(() => rowFor("Община Бургас"));
    expect(within(row).getByText("Официален")).toBeInTheDocument();
    expect(within(row).getByText("burgas.bg")).toBeInTheDocument();
    expect(within(row).getByText("Висок")).toBeInTheDocument();
    expect(within(row).getByRole("switch", { name: "Следи се: Община Бургас" })).toBeChecked();
    expect(within(row).getByRole("switch", { name: "Надежден за факти: Община Бургас" })).toBeChecked();

    // §5: the six columns, named the way §5 names them.
    for (const heading of ["Източник", "Тип", "Адрес / домейн", "Следи се", "Надежден за факти", "Приоритет"]) {
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
  });

  it("reads the registry from the API and owns no source list of its own", async () => {
    renderPage();
    await screen.findByText("Община Бургас");

    // §2: one canonical registry. The screen has no second source of truth.
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/settings/sources",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("method");
  });

  it("explains what Надежден за факти means, and never offers a trust score", async () => {
    renderPage();
    await screen.findByText("Община Бургас");

    // §6: the sentence is on the screen, not hidden behind a manual.
    expect(
      screen.getByText(/Когато източникът публикува информация от собствената си компетентност/),
    ).toBeInTheDocument();
    // §22: no AI credibility scoring anywhere in the surface.
    const body = document.body.textContent ?? "";
    for (const forbidden of ["Надежност", "доверие", "рейтинг", "Оценка"]) {
      expect(body).not.toContain(forbidden);
    }
  });

  it("§8 disables a source through the API and shows the server's answer", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "PUT" ? dataResponse(source({ monitored: false })) : dataResponse(REGISTRY),
    );

    renderPage();
    await screen.findByText("Община Бургас");
    await user.click(screen.getByRole("switch", { name: "Следи се: Община Бургас" }));

    await waitFor(() => expect(writeCount("PUT")).toBe(1));
    expect(fetchMock.mock.calls.find(([, i]) => (i as RequestInit)?.method === "PUT")?.[0])
      .toBe("/api/v1/settings/sources/burgas-municipality");
    expect(lastWriteBody("PUT")).toEqual({ monitored: false });
    // §32: the source is still listed. Disabling never removes it.
    expect(await screen.findByText("Община Бургас")).toBeInTheDocument();
  });

  it("§21 confirms once when authority is granted, and never when it is removed", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("БНР Бургас");

    // Grant: one confirmation, with the §21 sentence and both buttons.
    await user.click(screen.getByRole("switch", { name: "Надежден за факти: БНР Бургас" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(/ще може да служи като първична фактическа основа/),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Потвърди" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Отказ" })).toBeInTheDocument();
    // Nothing reached the server while the question was open.
    expect(writeCount("PUT")).toBe(0);

    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? dataResponse(source({ id: "bnr-burgas", factualAuthority: true }))
        : dataResponse(REGISTRY),
    );
    await user.click(within(dialog).getByRole("button", { name: "Потвърди" }));
    await waitFor(() => expect(writeCount("PUT")).toBe(1));
    // §22: only the explicit boolean the editor chose is sent.
    expect(lastWriteBody("PUT")).toEqual({ factualAuthority: true });
  });

  it("revoking authority is immediate, with no confirmation", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Община Бургас");

    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "PUT" ? dataResponse(source({ factualAuthority: false })) : dataResponse(REGISTRY),
    );
    await user.click(screen.getByRole("switch", { name: "Надежден за факти: Община Бургас" }));

    await waitFor(() => expect(writeCount("PUT")).toBe(1));
    expect(lastWriteBody("PUT")).toEqual({ factualAuthority: false });
    // Nothing is being granted, so there is nothing to confirm.
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("cancelling the authority confirmation changes nothing", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("БНР Бургас");

    await user.click(screen.getByRole("switch", { name: "Надежден за факти: БНР Бургас" }));
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Отказ" }));

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(writeCount("PUT")).toBe(0);
    // The toggle is still where the editor left it.
    expect(screen.getByRole("switch", { name: "Надежден за факти: БНР Бургас" })).not.toBeChecked();
  });

  it("§9 adds a source from six fields and never asks for an id", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "POST"
        ? dataResponse(source({ id: "nimh", name: "НИМХ", domain: "nimh.bg" }), 201)
        : dataResponse(REGISTRY),
    );

    renderPage();
    await screen.findByText("Община Бургас");
    await user.click(screen.getByRole("button", { name: "+ Добави източник" }));
    await screen.findByRole("heading", { name: "Нов източник" });

    // Exactly the §9 form, in editor language.
    expect(screen.getByLabelText("Име")).toBeInTheDocument();
    expect(screen.getByLabelText("URL / домейн")).toBeInTheDocument();
    expect(screen.getByLabelText("Тип")).toBeInTheDocument();
    expect(screen.getByLabelText("Приоритет")).toBeInTheDocument();
    // Both toggles are real switches, named as the §9 form names them.
    expect(screen.getByRole("switch", { name: "Следи се" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Надежден за факти" })).not.toBeChecked();
    // No internal registry field is on offer.
    for (const forbidden of ["source_id", "collector", "cadence", "factual_authority"]) {
      expect(document.body.textContent).not.toContain(forbidden);
    }

    await user.type(screen.getByLabelText("Име"), "НИМХ");
    await user.type(screen.getByLabelText("URL / домейн"), "nimh.bg");
    await user.selectOptions(screen.getByLabelText("Тип"), "official");
    // The sheet's own submit, not the toolbar's opener. The two differ only by
    // the toolbar's leading "+", so the match is anchored rather than substring.
    await user.click(screen.getByRole("button", { name: /^Добави източник$/ }));

    await waitFor(() => expect(writeCount("POST")).toBe(1));
    expect(fetchMock.mock.calls.find(([, i]) => (i as RequestInit)?.method === "POST")?.[0])
      .toBe("/api/v1/settings/sources");
    expect(lastWriteBody("POST")).toEqual({
      name: "НИМХ",
      address: "nimh.bg",
      kind: "official",
      monitored: true,
      factualAuthority: false,
      priority: "normal",
    });
  });

  it("§20 shows a refusal as the editor's own sentence", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "POST" ? errorResponse("Дайте име на източника.") : dataResponse(REGISTRY),
    );

    renderPage();
    await screen.findByText("Община Бургас");
    await user.click(screen.getByRole("button", { name: "+ Добави източник" }));
    await user.click(screen.getByRole("button", { name: /^Добави източник$/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Дайте име на източника.");
    // §20: no schema sentence leaks through the boundary.
    expect(document.body.textContent).not.toContain("source_id");
  });

  it("§14 filters and searches over what the editor can already see", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Община Бургас");

    await user.click(screen.getByRole("button", { name: "Следени" }));
    expect(screen.queryByText("Регионална библиотека „Пейо Яворов“")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Официални" }));
    expect(screen.getByText("Община Бургас")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Всички" }));
    await user.type(screen.getByLabelText("Търси източник"), "бнр");
    expect(screen.getByText("БНР Бургас")).toBeInTheDocument();
    expect(screen.queryByText("Община Бургас")).toBeNull();
  });

  it("§10 opens a small editor with only the four changeable fields", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "PUT" ? dataResponse(source()) : dataResponse(REGISTRY),
    );

    renderPage();
    await screen.findByText("Община Бургас");
    await user.click(within(rowFor("Община Бургас")).getByRole("button", { name: "Редактирай" }));
    expect(await screen.findByLabelText("Име")).toHaveValue("Община Бургас");
    expect(screen.getByLabelText("Приоритет")).toBeInTheDocument();
    // The domain is shown for recognition, never as an editable field.
    expect(screen.queryByLabelText(/домейн/i)).toBeNull();

    await user.selectOptions(screen.getByLabelText("Приоритет"), "low");
    await user.click(screen.getByRole("button", { name: "Запиши" }));

    await waitFor(() => expect(writeCount("PUT")).toBe(1));
    expect(lastWriteBody("PUT")).toEqual({
      name: "Община Бургас",
      priority: "low",
      monitored: true,
      factualAuthority: true,
    });
  });

  it("§15 shows a quiet Проблем and never a collector internal", async () => {
    fetchMock.mockResolvedValue(
      dataResponse(
        projection([
          source({
            id: "burgas-regional-administration",
            name: "Областна администрация Бургас",
            health: { status: "problem", label: "Проблем", lastSuccessAt: "" },
          }),
        ]),
      ),
    );
    renderPage();

    expect(await screen.findByText("Проблем")).toBeInTheDocument();
    const body = document.body.textContent ?? "";
    for (const forbidden of ["HTTPError", "Traceback", "503", "Exception"]) {
      expect(body).not.toContain(forbidden);
    }
  });

  it("never offers hard delete, and uses no publishing vocabulary", async () => {
    renderPage();
    await screen.findByText("Община Бургас");

    // §11: `Изключи` is the removal; there is no destructive action anywhere.
    expect(screen.queryByRole("button", { name: /Премахни|Изтрий|Удалели/ })).toBeNull();
    // §32: this screen is not a publishing surface.
    for (const forbidden of ["Публикувай", "Публикува", "Изпрати", "Одобри", "CMS", "Експорт"]) {
      expect(document.body.textContent).not.toContain(forbidden);
    }
  });

  it("keeps a disabled source visible instead of hiding it", async () => {
    renderPage();
    await screen.findByText("Регионална библиотека „Пейо Яворов“");

    // §8/§32: the row is still there and still readable, just switched off.
    expect(screen.getByRole("switch", { name: "Следи се: Регионална библиотека „Пейо Яворов“" }))
      .not.toBeChecked();
    expect(screen.getByText("1 изключени")).toBeInTheDocument();
  });

  it("recovers calmly when the registry cannot be read", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(errorResponse("Вътрешна грешка. Опитайте отново.", 500));
    renderPage();

    expect(await screen.findByText("Източниците не можа да се заредят")).toBeInTheDocument();
    fetchMock.mockResolvedValue(dataResponse(REGISTRY));
    await user.click(screen.getByRole("button", { name: "Опитайте отново" }));
    expect(await screen.findByText("Община Бургас")).toBeInTheDocument();
  });
});
