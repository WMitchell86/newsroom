import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ArticleDetail, StoryDetail } from "../api/dto";
import { ArticleWorkspace } from "../pages/ArticleWorkspace";
import { StoryWorkspace } from "../pages/StoryWorkspace";
import { activePreparationArticle, storyDetail } from "./fixtures";
import { renderWithProviders } from "./render";

/**
 * V1.2-G2.2 §14-§17 — the editor-facing research and Focus contract.
 *
 * These are the four defects the owner found while using the real product:
 * a research round that outran a 2-second budget and looked failed, an
 * operational refusal dressed as missing evidence, an unassessed Story that
 * read as a mysterious error, and a Focus that demanded a second click.
 */

const fetchMock = vi.fn();

function dataResponse(data: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => ({ data }) } as Response;
}

function errorResponse(code: string, message: string, status = 503) {
  return {
    ok: false,
    status,
    json: async () => ({ error: { code, message, retryable: true, fieldErrors: [] } }),
  } as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

function storyRoute() {
  return (
    <Routes>
      <Route path="/stories/:storyId" element={<StoryWorkspace />} />
      <Route path="/articles/:articleId" element={<ArticleWorkspace />} />
    </Routes>
  );
}

const unassessedStory: StoryDetail = {
  ...storyDetail,
  id: "s-research-ux",
  factsAndSources: [],
  availableActions: ["REVIEW", "RESEARCH_MORE"],
  missingInformation: { items: [], assessedAt: null, evidenceStatus: "unassessed" },
};

describe("V1.2-G2.2 — the research operation is followed, not timed out", () => {
  it("stays in progress well past the old ~2 second budget and one operation only", async () => {
    // §1: a real round performs a search and opens pages. The UI must remain in
    // the pending state for as long as the backend is still working.
    const gate: { release?: () => void } = {};
    const running = new Promise<void>((resolve) => {
      gate.release = resolve;
    });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/research")) {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-ux" } }) } as Response;
      }
      if (url.endsWith("/operations/op-ux")) {
        await running;
        return dataResponse({ status: "succeeded", result: unassessedStory });
      }
      return dataResponse(unassessedStory);
    });
    const user = userEvent.setup();
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${unassessedStory.id}`] });
    await screen.findByRole("heading", { level: 1, name: unassessedStory.title });

    await user.click(screen.getByRole("button", { name: "Проучи още" }));

    // Several seconds of real time, with the operation still running.
    await screen.findByRole("button", { name: "Проучва се…" });
    for (let tick = 0; tick < 6; tick += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    expect(screen.getByRole("button", { name: "Проучва се…" })).toBeDisabled();
    // No false failure sentence at any point.
    expect(document.body.textContent).not.toContain("Проучването все още не е готово");
    expect(screen.queryByRole("alert")).toBeNull();

    gate.release?.();
    // Completion arrives and the Story refetches itself.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Проучи още" })).toBeEnabled(),
    );
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST");
    expect(posts).toHaveLength(1);
  });

  it("says the round continues and offers one reattach instead of a retry", async () => {
    // §2: the bounded-wait behaviour itself is proven in the client suite (the
    // real 180-attempt budget). This test proves the EDITOR contract for that
    // outcome: the operation is still running, the editor is told so, and the
    // only way forward is a reattach to the SAME operation.
    const client = await import("../api/client");
    const researchSpy = vi.spyOn(client, "researchMoreStory").mockResolvedValue({
      status: "continuing",
      operationToken: "op-cont",
    });
    const statusSpy = vi.spyOn(client, "checkResearchStatus").mockResolvedValue({
      status: "completed",
      story: unassessedStory,
    });
    fetchMock.mockResolvedValue(dataResponse(unassessedStory));
    const user = userEvent.setup();
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${unassessedStory.id}`] });
    await screen.findByRole("heading", { level: 1, name: unassessedStory.title });

    await user.click(screen.getByRole("button", { name: "Проучи още" }));

    await waitFor(() => expect(screen.getByText(/Проучването продължава/)).toBeVisible());
    // §1: the pending sentence is gone, and so is the old false failure text.
    expect(screen.queryByRole("button", { name: "Проучва се…" })).toBeNull();
    expect(document.body.textContent).not.toContain("Проучването все още не е готово");
    expect(screen.queryByRole("alert")).toBeNull();

    // §2: one control, and it reattaches instead of starting a second round.
    await user.click(screen.getByRole("button", { name: "Провери статуса" }));
    await waitFor(() => expect(statusSpy).toHaveBeenCalledWith("op-cont"));
    expect(researchSpy).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByText(/Проучването продължава/)).toBeNull(),
    );
  });
});

describe("V1.2-G2.2 — an operational refusal is never an evidence statement", () => {
  it.each([
    ["RESEARCH_UNAVAILABLE", "Автоматичното проучване временно не е налично."],
    ["RESEARCH_QUOTA_EXHAUSTED", "Лимитът за автоматично проучване е изчерпан за момента."],
  ])("renders %s as operational wording", async (code, message) => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") return errorResponse(code, message);
      return dataResponse(unassessedStory);
    });
    const user = userEvent.setup();
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${unassessedStory.id}`] });
    await screen.findByRole("heading", { level: 1, name: unassessedStory.title });

    await user.click(screen.getByRole("button", { name: "Проучи още" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(message);
    // §3: never dressed up as missing evidence, and no internals.
    for (const forbidden of [
      "не е намерен отворен източник",
      "няма отворен източник",
      "Историята трябва първо да бъде проучена",
      "429",
      "route",
      "модел",
    ]) {
      expect(document.body.textContent?.toLowerCase()).not.toContain(forbidden.toLowerCase());
    }
  });

  it("leaves the existing evidence rendering untouched by an operational failure", async () => {
    const assessed: StoryDetail = {
      ...storyDetail,
      id: "s-assessed-ux",
      availableActions: ["RESEARCH_MORE"],
      missingInformation: {
        items: [{ id: "gap-1", question: "Кога точно започва ремонтът?", kind: "missing_fact", blocking: true }],
        assessedAt: "2026-09-25T09:32:00Z",
        evidenceStatus: "assessed",
      },
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return errorResponse("RESEARCH_UNAVAILABLE", "Автоматичното проучване временно не е налично.");
      }
      return dataResponse(assessed);
    });
    const user = userEvent.setup();
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${assessed.id}`] });
    await screen.findByRole("heading", { level: 1, name: assessed.title });

    await user.click(screen.getByRole("button", { name: "Проучи още" }));
    await screen.findByRole("alert");

    // §3/§12: a refused round adds nothing and removes nothing.
    expect(screen.getByText(assessed.factsAndSources[0]!.text)).toBeVisible();
    expect(screen.getByText("Кога точно започва ремонтът?")).toBeVisible();
  });
});

describe("V1.2-G2.2 — the Focus needs content, not a confirmation click", () => {
  /**
   * A preparation projection with BOTH action lists set, because the canonical
   * `availableActions` the component reads lives on the Article, while the
   * readiness block carries the same decision for the editor.
   */
  function preparation(
    readiness: ArticleDetail["preparation"],
    availableActions: ArticleDetail["availableActions"],
  ): ArticleDetail {
    return {
      ...activePreparationArticle,
      availableActions,
      preparation: readiness!,
    };
  }

  it("has no focus-confirmation control anywhere on the preparation surface", async () => {
    fetchMock.mockResolvedValue(dataResponse(activePreparationArticle));
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );
    await screen.findByRole("heading", { name: "Редакционен фокус" });

    // §5: the concept is gone, not renamed.
    for (const label of [/Потвърди фокуса/i, /Избери фокус/i, /Промени фокуса/i]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
    expect(document.body.textContent).not.toMatch(/очаква редакторско решение/);
    // The field is still there and still editable: it is the whole interaction.
    expect(screen.getByRole("textbox", { name: "Редакционен фокус" })).toBeEnabled();
  });

  it("saves a non-empty Focus on blur and keeps the Draft action available", async () => {
    const ready = preparation(
      {
        focusConfirmed: true,
        draftReadiness: { code: "DRAFT_ELIGIBLE", message: "Има достатъчно потвърдена информация за чернова." },
        blockingGaps: [],
        nonBlockingGaps: [],
        draftEligible: true,
        draftFailure: null,
        availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"],
      },
      ["CHANGE_FOCUS", "MAKE_DRAFT"],
    );
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/focus")) return dataResponse(ready);
      return dataResponse(ready);
    });
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );
    await screen.findByRole("heading", { name: "Редакционен фокус" });

    const focus = screen.getByRole("textbox", { name: "Редакционен фокус" });
    await user.clear(focus);
    await user.type(focus, "Ще разкажем защо парите за градините са важни.");
    await user.tab();

    // §6: the save IS the confirmation, and Draft readiness follows the text.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/articles/${activePreparationArticle.id}/focus`,
      expect.objectContaining({ method: "PUT" }),
    ));
    expect(screen.getByRole("button", { name: "Направи чернова" })).toBeEnabled();
  });

  it("refuses the Draft with one clear sentence when the Focus is empty", async () => {
    // §7: absent action plus one actionable message — no confirmation concept.
    const empty = preparation(
      {
        focusConfirmed: false,
        draftReadiness: {
          code: "FOCUS_NOT_CONFIRMED",
          message: "Добавете редакционен фокус, за да създадете чернова.",
        },
        blockingGaps: [],
        nonBlockingGaps: [],
        draftEligible: false,
        draftFailure: null,
        availableActions: ["SELECT_FOCUS"],
      },
      ["SELECT_FOCUS"],
    );
    fetchMock.mockResolvedValue(dataResponse(empty));
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );
    await screen.findByRole("heading", { name: "Фактическа основа" });

    // §7: one clear sentence, no Draft action, and the field is right there —
    // adding a Focus is the whole remedy, with no confirmation step after it.
    expect(screen.getByText("Добавете редакционен фокус, за да създадете чернова.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Направи чернова" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Редакционен фокус" })).toBeEnabled();
  });

  it("presents an unassessed Story as a preparation step with its own action", async () => {
    // §4: not an error — one sentence and one next action.
    const unassessed = preparation(
      {
        focusConfirmed: true,
        draftReadiness: {
          code: "STORY_UNASSESSED",
          message: "За чернова първо е нужно проучване на историята.",
        },
        blockingGaps: [],
        nonBlockingGaps: [],
        draftEligible: false,
        draftFailure: null,
        availableActions: ["CHANGE_FOCUS", "RESEARCH_MORE"],
      },
      ["CHANGE_FOCUS", "RESEARCH_MORE"],
    );
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/research")) return dataResponse(storyDetail);
      return dataResponse(unassessed);
    });
    renderWithProviders(
      <Routes><Route path="/articles/:articleId" element={<ArticleWorkspace />} /></Routes>,
      { initialEntries: [`/articles/${activePreparationArticle.id}`] },
    );
    await screen.findByRole("heading", { name: "Фактическа основа" });

    expect(screen.getByText("За чернова първо е нужно проучване на историята.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Проучи историята" })).toBeEnabled();
    // And the Story itself stays one click away.
    expect(screen.getByRole("link", { name: "Отвори историята" })).toHaveAttribute(
      "href",
      `/stories/${activePreparationArticle.story.id}`,
    );
  });
});

describe("V1.2-G2.2 — the original collected article is one click away", () => {
  it("offers the backend's original publication in the Story header", async () => {
    fetchMock.mockResolvedValue(dataResponse(storyDetail));
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${storyDetail.id}`] });
    await screen.findByRole("heading", { level: 1, name: storyDetail.title });

    const original = document.querySelector("[data-story-original]") as HTMLAnchorElement;
    expect(original).not.toBeNull();
    expect(original).toHaveTextContent("Отвори оригинала");
    expect(original).toHaveAttribute("href", storyDetail.publications[0]!.url);
    expect(original).toHaveAttribute("target", "_blank");
    expect(original.getAttribute("rel")).toContain("noreferrer");
  });

  it("renders no original action when the Story has no origin publication", async () => {
    const withoutOrigin = { ...storyDetail, originPublicationId: null };
    fetchMock.mockResolvedValue(dataResponse(withoutOrigin));
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${withoutOrigin.id}`] });
    await screen.findByRole("heading", { level: 1, name: withoutOrigin.title });

    expect(document.querySelector("[data-story-original]")).toBeNull();
  });

  it("gives every publication its own external link without implying evidence", async () => {
    fetchMock.mockResolvedValue(dataResponse(storyDetail));
    renderWithProviders(storyRoute(), { initialEntries: [`/stories/${storyDetail.id}`] });
    await screen.findByRole("heading", { level: 1, name: storyDetail.title });

    const section = screen.getByRole("heading", { name: "Публикации" }).closest("section")!;
    const links = within(section).getAllByRole("link", { name: /Отвори/ });
    expect(links).toHaveLength(storyDetail.publications.length);
    for (const link of links) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toContain("noreferrer");
      expect(link.getAttribute("href")).toMatch(/^https:/);
    }
    // §10/§18: a linked publication is navigation, never a verification claim.
    const text = section.textContent ?? "";
    for (const forbidden of ["Надежден", "потвърден", "Verified", "проверен източник"]) {
      expect(text).not.toContain(forbidden);
    }
  });
});
