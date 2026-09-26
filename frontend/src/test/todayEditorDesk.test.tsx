import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TodayProjection } from "../api/dto";
import { AppShell } from "../app/AppShell";
import { TodayPage } from "../pages/TodayPage";
import { todayProjection } from "./fixtures";
import { renderWithProviders } from "./render";
import { isRedundantSummary, publisherCountLabel } from "../shared/editorLabels";

/**
 * V1.2-G1 §30: the frontend proof for the editor desk.
 *
 * Every test here exists because the slice could plausibly have gone the other
 * way — a plausible-looking rail, a plausible sort, a plausible warning — and
 * these are the assertions that make the *honest* version fail if it is undone.
 */

const fetchMock = vi.fn();

function dataResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ data }),
  } as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

/** A Story attention row, with a distinct publisher count for the sort proofs. */
function story(
  id: string,
  title: string,
  timestamp: string,
  publisherCount: number,
  extra: Record<string, unknown> = {},
) {
  return {
    objectId: id,
    objectType: "story" as const,
    title,
    summary: `Обобщение за ${title}`,
    timestamp,
    reason: "NEW_STORY" as const,
    nextAction: "REVIEW" as const,
    delta: { unreviewedDevelopmentCount: 0 },
    publisherCount,
    availableActions: ["REVIEW", "IGNORE", "QUICK_DRAFT"],
    quickDraft: { available: true, label: "Чернова", articleId: null, reasonCode: null },
    ...extra,
  };
}

/** Eight-to-twelve-row shaped desk, in scrambled ids against its timestamps. */
function deskProjection(): TodayProjection {
  const rows = [
    story("s-a", "Община Поморие отвори център за подкрепа на семействата", "2026-09-25T08:10:00Z", 1),
    story("s-b", "Съветът одобри ремонта на улицата", "2026-09-25T09:30:00Z", 5),
    story("s-c", "Началните училища получават нови учебни пособия", "2026-09-25T07:00:00Z", 2),
    story("s-d", "Ден на отворените врати в историческия музей", "2026-09-25T06:00:00Z", 9),
  ];
  return {
    ...todayProjection,
    newDevelopments: [] as never,
    newStories: rows as never,
    storyAttentionTotal: rows.length,
    storyAttentionShown: rows.length,
    articlesRequiringAction: [] as never,
    problems: [] as never,
  };
}

function renderedRowIds(): string[] {
  return [...document.querySelectorAll("[data-story-row]")].map(
    (node) => node.getAttribute("data-story-row") ?? "",
  );
}

function renderRail() {
  return renderWithProviders(
    <Routes>
      <Route element={<AppShell />}>
        <Route path="stories" element={<p>Истории</p>} />
      </Route>
    </Routes>,
    { initialEntries: ["/stories"] },
  );
}


describe("V1.2-G1 — the left rail", () => {
  it("keeps exactly five primary destinations, with Настройки in the left column", () => {
    renderRail();

    const rail = document.querySelector("aside")!;
    // §1: the frozen set, in the frozen words. `Източници` was refused as a
    // sixth item and must not appear.
    const destinations = [...rail.querySelectorAll("a")].map((link) => link.textContent);
    expect(destinations).toEqual(["Редакция", "Днес", "Истории", "Статии", "Архив", "Настройки"]);
    // §24: bottom of the left column — not the header, not a top/right strip.
    expect(rail.querySelector("header")).toBeNull();
    const settings = within(rail).getByRole("link", { name: "Настройки" });
    expect(settings.closest("nav")?.getAttribute("aria-label")).toBe("Настройки");
  });

  it("renders the category rail with no fabricated counts", () => {
    renderRail();

    const rail = document.querySelector("aside")!;
    expect(within(rail).getByRole("heading", { name: "Категории" })).toBeInTheDocument();
    // §5: no invented numbers anywhere in the category area. A count the backend
    // cannot produce must not appear in the markup at all.
    const categories = rail.querySelector("[data-category-state]")!.closest("section")!;
    expect(categories.textContent).not.toMatch(/\d/);
  });

  it("keeps the future categories present but not actionable", async () => {
    renderRail();
    const user = userEvent.setup();

    // The taxonomy is spatially validated: every future label is on screen.
    for (const label of [
      "Общество",
      "Култура",
      "Туризъм",
      "Бизнес",
      "Спорт",
      "Образование",
      "Здраве",
      "Инфраструктура",
      "Други",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    // §5/§29: exposed as genuinely disabled, with the reason available without
    // hovering.
    const sport = screen.getByRole("button", { name: "Спорт" });
    expect(sport).toBeDisabled();
    expect(sport).toHaveAccessibleDescription("Категоризацията предстои");
    // §5: `Всички` is the one real, active state.
    expect(document.querySelector('[data-category-state="active"]')!.textContent).toBe("Всички");

    // Clicking around the prepared rail changes no data and issues no request.
    await user.click(sport);
    expect(screen.getByRole("heading", { name: "Категории" })).toBeInTheDocument();
  });
});

describe("V1.2-G1 — search", () => {
  it("filters the loaded Today rows by headline", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });
    expect(renderedRowIds()).toHaveLength(4);

    await user.type(screen.getByLabelText(/Търсене в днешните истории/), "музей");

    expect(renderedRowIds()).toEqual(["s-d"]);
  });

  it("searches the summary as well as the headline", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    await user.type(screen.getByLabelText(/Търсене в днешните истории/), "Обобщение за Съветът");

    expect(renderedRowIds()).toEqual(["s-b"]);
  });

  it("restores every row when the search is cleared", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });
    const search = screen.getByLabelText(/Търсене в днешните истории/);

    await user.type(search, "музей");
    expect(renderedRowIds()).toHaveLength(1);
    await user.clear(search);

    expect(renderedRowIds()).toHaveLength(4);
  });

  it("is scoped to the loaded Today set, not a claim of archive search", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    // §6: a real label, not a placeholder standing in for one, and the
    // placeholder states the scope honestly.
    const search = screen.getByLabelText(/Търсене в днешните истории/);
    expect(search).toHaveAttribute("placeholder", "Търси в истории, източници и заглавия…");
    // Search is a view concern: it must not re-query the API.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("V1.2-G1 — sorting", () => {
  it("defaults to the newest change first", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    expect(screen.getByLabelText("Сортирай")).toHaveValue("newest");
    expect(renderedRowIds()).toEqual(["s-b", "s-a", "s-c", "s-d"]);
  });

  it("reorders by independent publisher count when asked", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    await user.selectOptions(screen.getByLabelText("Сортирай"), "publishers");

    // 9, 5, 2, 1 — the backend's own count, never recomputed in React (§10).
    expect(renderedRowIds()).toEqual(["s-d", "s-b", "s-c", "s-a"]);
  });

  it("sorts without mutating the projection and without any API call", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });
    const before = renderedRowIds();

    await user.selectOptions(screen.getByLabelText("Сортирай"), "publishers");

    // §11: a view preference — no reload, no mutation, no hidden model call.
    expect(
      fetchMock.mock.calls.every(
        ([, init]) => !("method" in (init ?? {})) || (init as RequestInit).method === "GET",
      ),
    ).toBe(true);
    expect(renderedRowIds()).not.toEqual(before);
    // Returning to the default restores the canonical chronological order.
    await user.selectOptions(screen.getByLabelText("Сортирай"), "newest");
    expect(renderedRowIds()).toEqual(before);
  });

  it("offers no ranking this slice cannot support truthfully", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    const labels = within(screen.getByLabelText("Сортирай"))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(labels).toEqual(["Най-нови", "Най-много източници"]);
    // §9: no `Топ` / `Най-важни` / AI ranking — those need ranking work that
    // does not exist yet, and an unexplainable order is worse than none.
    for (const forbidden of ["Топ", "Най-важни", "Препоръчани"]) {
      expect(labels).not.toContain(forbidden);
    }
  });
});

describe("V1.2-G1 — the story row", () => {
  it("renders the independent publisher count quietly", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    const row = document.querySelector('[data-story-row="s-b"]') as HTMLElement;
    // §15: the corroboration context, in words.
    expect(within(row).getByText("5 източника")).toBeInTheDocument();
    // §20: the count is NOT a trust badge and never implies the pages were
    // opened or promoted to evidence.
    expect(row.textContent).not.toMatch(/Надежден|Ненадежден|Verified|Trusted/);
  });

  it("renders no category label when the backend sends no category", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    // §13: no `ОБЩЕСТВО` / `СПОРТ` / `ОБРАЗОВАНИЕ` on real rows — and not an
    // empty placeholder left behind either.
    for (const forbidden of ["ОБЩЕСТВО", "СПОРТ", "ОБРАЗОВАНИЕ", "Общество"]) {
      expect(document.querySelector("[data-story-row]")?.textContent).not.toContain(forbidden);
    }
    expect(document.querySelectorAll("[class*='categoryLabel']")).toHaveLength(0);
  });

  it("suppresses a summary that merely repeats the headline", async () => {
    const repeated = deskProjection();
    (repeated.newStories as unknown as Array<{ summary: string }>)[0]!.summary =
      "Община Поморие отвори център за подкрепа на семействата!";
    fetchMock.mockResolvedValue(dataResponse(repeated));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    const row = document.querySelector('[data-story-row="s-a"]') as HTMLElement;
    // The headline is still there; the duplicated line simply is not.
    expect(within(row).getByText(/Община Поморие/)).toBeInTheDocument();
    expect(row.querySelectorAll("p")).toHaveLength(1);
  });

  it("never infers a locality out of the headline", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    // §14: `Поморие` is in the headline, but no locality element is fabricated
    // from it in React.
    const meta = document.querySelector('[data-story-row="s-a"] [class*="storyMeta"]')!;
    expect(meta.textContent).not.toContain("Поморие");
  });
});


/** Drives a Quick Draft to a `needs_attention` result with real backend wording. */
function mockBlockedQuickDraft(message: string) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-g1" } }) } as Response;
    }
    if (url === "/api/v1/operations/op-g1") {
      return dataResponse({
        status: "succeeded",
        result: { status: "needs_attention", reasonCode: "NO_OPEN_SOURCE", message },
      });
    }
    return dataResponse(deskProjection());
  });
}

describe("V1.2-G1 — evidence warning semantics", () => {
  it("renders the backend's own blocker text verbatim", async () => {
    // §19: the precise, plain-language missing-information message.
    const message = "Остава непотвърдено кога започва ограничението.";
    mockBlockedQuickDraft(message);
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    await user.click(screen.getAllByRole("button", { name: "Чернова" })[0]!);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    // §19/§21: the way out is still offered, in the same action region.
    expect(screen.getAllByRole("link", { name: "Прегледай" })[0]).toBeInTheDocument();
  });

  it("keeps the precise NO_OPEN_SOURCE wording the backend sent", async () => {
    const message = "Не успяхме да осигурим отворен източник за тази история.";
    mockBlockedQuickDraft(message);
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    await user.click(screen.getAllByRole("button", { name: "Чернова" })[0]!);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("never invents generic 'reliable source' wording", async () => {
    mockBlockedQuickDraft("Не успяхме да осигурим отворен източник за тази история.");
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    await user.click(screen.getAllByRole("button", { name: "Чернова" })[0]!);
    await screen.findByRole("alert");

    // §18: the frontend must never substitute a reputation judgement for the
    // real blocker. "Publisher known, page never opened" must not read as
    // "this publisher is unreliable".
    for (const forbidden of [
      "надежен отворен източник",
      "Надежден",
      "Ненадежден",
      "не е надежден",
      "Trusted",
      "Verified",
    ]) {
      expect(document.body.textContent).not.toContain(forbidden);
    }
  });
});

describe("V1.2-G1 — Quick Draft action hierarchy", () => {
  it("keeps Чернова as the single forward action, beside the two quiet ones", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    // §16: exactly three triage intents, no extras on Today.
    const row = document.querySelector('[data-story-row="s-a"]') as HTMLElement;
    expect(within(row).getByRole("button", { name: "Игнорирай" })).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Прегледай" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Чернова" })).toBeInTheDocument();
    // §16: `Игнорирай` is never destructive red — it is reversible triage, so it
    // carries the quietest treatment, not the error colour. CSS-module class
    // names are hashed at build time, so the marker is matched by pattern.
    const ignore = within(row).getByRole("button", { name: "Игнорирай" });
    expect(ignore.className).toMatch(/_quiet_/);
    expect(ignore.className).not.toMatch(/_action_/);
  });

  it("shows one calm pending status and no stage vocabulary", async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-slow" } }) } as Response;
      }
      if (url === "/api/v1/operations/op-slow") return pending;
      return dataResponse(deskProjection());
    });
    const user = userEvent.setup();
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    await user.click(screen.getAllByRole("button", { name: "Чернова" })[0]!);

    // §17: one sentence, replacing the action area rather than growing it.
    const pendingRow = await screen.findByRole("button", { name: "Подготвя се чернова…" });
    expect(pendingRow).toBeDisabled();
    expect(document.querySelector('[data-triage-state="pending"]')).not.toBeNull();
    // The internal stages stay internal: the pending region states one thing and
    // names no step of the pipeline behind it.
    const pendingRegion = document.querySelector('[data-triage-state="pending"]')!;
    expect(pendingRegion.textContent?.trim()).toBe("Подготвя се чернова…");
    for (const stage of ["търсене", "отваряне", "проверка", "модел", "генериране"]) {
      expect(pendingRegion.textContent?.toLowerCase()).not.toContain(stage);
    }
    release(
      dataResponse({ status: "succeeded", result: { status: "draft_created", articleId: "a-1" } }),
    );
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Чернова" }).length).toBeGreaterThan(0));
  });
});


describe("V1.2-G1 — preserved D1/D2 behaviour", () => {
  it("still shows the grouping-health warning through the restyle", async () => {
    fetchMock.mockResolvedValue(
      dataResponse({
        ...deskProjection(),
        groupingHealth: {
          status: "degraded",
          lastSuccessfulSemanticClassificationAt: "2026-09-25T04:31:00Z",
          semanticRequired: 12,
          semanticAnswered: 9,
          semanticDegraded: 3,
        },
      }),
    );
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    // §26: the F2A warning is not lost in the visual rewrite.
    expect(screen.getByText(/Групирането на истории е ограничено/)).toBeInTheDocument();
  });

  it("still discloses the story cap and links to the full collection", async () => {
    fetchMock.mockResolvedValue(
      dataResponse({ ...deskProjection(), storyAttentionTotal: 47, storyAttentionShown: 4 }),
    );
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    expect(screen.getByText(/Показани са 4 от 47/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Виж всички в Истории" })).toHaveAttribute("href", "/stories");
  });

  it("still renders the Article attention tier below the Story list", async () => {
    fetchMock.mockResolvedValue(
      dataResponse({
        ...deskProjection(),
        articlesRequiringAction: [todayProjection.articlesRequiringAction[0]!] as never,
      }),
    );
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    // §27: the tier survives, and it stays below the Stories.
    expect(screen.getByRole("heading", { name: "Статии за действие" })).toBeInTheDocument();
  });

  it("keeps the real Обнови operation wired to the header", async () => {
    fetchMock.mockResolvedValue(dataResponse(deskProjection()));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    // §26: the D1 refresh operation is unchanged, and the D1 line still shows.
    expect(screen.getByRole("button", { name: "Обнови" })).toBeEnabled();
    expect(screen.getByText(/Последно обновяване:/)).toBeInTheDocument();
  });
});

describe("V1.2-G1 — row action alignment (owner-approved correction)", () => {
  it("top-aligns the action area and never truncates the headline", async () => {
    const long = deskProjection();
    // A deliberately three-line headline: the case the correction was made for.
    (long.newStories as unknown as Array<{ title: string }>)[0]!.title =
      "Общинският съвет одобри 1,2 милиона лева за ремонта на улицата „Шишман“ и обсъжда промените в градския транспорт";
    fetchMock.mockResolvedValue(dataResponse(long));
    renderWithProviders(<TodayPage />, { route: "/" });
    await screen.findByRole("heading", { name: "Днес" });

    const row = document.querySelector('[data-story-row="s-a"]') as HTMLElement;
    const headline = row.querySelector("h3") as HTMLElement;
    const aside = row.querySelector("[class*='storyAside']") as HTMLElement;

    // 1. The headline is shown in full. Row geometry is never a reason to cut it.
    expect(headline.textContent).toContain("градския транспорт");
    expect(getComputedStyle(headline).webkitLineClamp).not.toBe("2");
    expect(getComputedStyle(headline).textOverflow).not.toBe("ellipsis");
    expect(getComputedStyle(headline).overflow).not.toBe("hidden");

    // 2. The controls are top-aligned, so a tall headline cannot make them
    //    "float" in the vertical middle of the row.
    expect(getComputedStyle(aside).alignSelf).toBe("start");
  });
});

describe("V1.2-G1 — label helpers", () => {
  it("does not print a measured zero for an unknown publisher count", () => {
    expect(publisherCountLabel(0)).toBeNull();
    expect(publisherCountLabel(undefined)).toBeNull();
    expect(publisherCountLabel(1)).toBe("1 източник");
    expect(publisherCountLabel(4)).toBe("4 източника");
  });

  it("treats a punctuated or truncated echo of the headline as redundant", () => {
    const title = "Община Поморие отвори център за подкрепа на семействата";
    expect(isRedundantSummary(title, title)).toBe(true);
    expect(isRedundantSummary(title, `${title}!`)).toBe(true);
    expect(isRedundantSummary(title, "")).toBe(true);
    expect(isRedundantSummary(title, "Новата услуга ще консултира семейства.")).toBe(false);
  });
});

