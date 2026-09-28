import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ArticleDetail } from "../api/dto";
import { ArticleWorkspace } from "../pages/ArticleWorkspace";
import {
  activeDraftArticle,
  activePreparationArticle,
  activeReadyArticle,
  failedPreparationArticle,
  storyDetail,
} from "./fixtures";
import { renderWithProviders } from "./render";

/**
 * V1.2-G3 §35-§37 — the Article / Draft workspace contract.
 *
 * G3 is a visual and interaction slice over a backend that was already
 * authoritative, so these tests are mostly NEGATIVE: they assert that the page
 * did not grow a second body control, a second title field, a second writer,
 * a fake save button, a new state, or any publication vocabulary.
 *
 * What is frozen here:
 *   Preparation  a launchpad, not a wizard; the Focus arrives already filled;
 *   Draft        one writing surface that dominates; support on the side;
 *   Ready        calm, with exactly one forward action and no publishing.
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

function articleRoute() {
  return (
    <Routes>
      <Route path="/articles/:articleId" element={<ArticleWorkspace />} />
      <Route path="/stories/:storyId" element={<p>История</p>} />
      <Route path="/articles" element={<p>Списък със статии</p>} />
      <Route path="/archive/:articleId" element={<p>Архивна статия</p>} />
    </Routes>
  );
}

function renderArticle(article: ArticleDetail) {
  fetchMock.mockResolvedValue(dataResponse(article));
  return renderWithProviders(articleRoute(), { initialEntries: [`/articles/${article.id}`] });
}

/** A Preparation Article that is genuinely ready to become a Draft. */
function eligiblePreparation(overrides: Partial<ArticleDetail> = {}): ArticleDetail {
  return {
    ...activePreparationArticle,
    editorialFocus: {
      text: "Показваме какво е готово по ремонта и какво още трябва да бъде уточнено с община Бургас.",
      confirmedAt: "2026-09-25T11:00:00Z",
    },
    preparation: {
      ...activePreparationArticle.preparation!,
      focusConfirmed: true,
      // §D2: the backend's own deterministic alternatives.
      focusAlternatives: [
        "Кога започва ремонтът и какво остава неуточнено дори след началото му.",
        "Община Бургас обяви октомври, но не публикува точната дата.",
      ],
      draftEligible: true,
      draftReadiness: {
        code: "DRAFT_ELIGIBLE",
        message: "Има достатъчно потвърдена информация за чернова.",
      },
      availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"],
    },
    availableActions: ["CHANGE_FOCUS", "MAKE_DRAFT"],
    nextAction: {
      action: "MAKE_DRAFT",
      reasonCode: "DRAFT_ELIGIBLE",
      label: "Направи чернова",
      primary: true,
    },
    ...overrides,
  };
}

describe("V1.2-G3 §35 — Preparation is a launchpad, not a form", () => {
  it("opens with a useful Focus already filled and no interaction required", async () => {
    // §11: the ideal path is DO NOTHING -> «Направи чернова».
    renderArticle(eligiblePreparation());
    const focus = await screen.findByRole("textbox", { name: "Редакционен фокус" });
    expect(focus).toHaveValue(activePreparationArticle.editorialFocus.text);
    // No confirmation, no apply, no wizard step of its own.
    for (const forbidden of [/Потвърди/i, /Избери фокус/i, /Промени фокуса/i, /Напред/i, /Стъпка/i]) {
      expect(screen.queryByRole("button", { name: forbidden })).toBeNull();
    }
    expect(screen.getByRole("button", { name: "Направи чернова" })).toBeEnabled();
  });

  it("shows the backend's alternatives and saves an adopted one in one click", async () => {
    // §11: one click replaces AND saves. There is no second confirm step.
    const article = eligiblePreparation();
    const alternative = article.preparation!.focusAlternatives[0]!;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/focus")) {
        return dataResponse({
          ...article,
          editorialFocus: { text: alternative, confirmedAt: "2026-09-25T11:10:00Z" },
        });
      }
      return dataResponse(article);
    });
    const user = userEvent.setup();
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${article.id}`] });
    const focus = await screen.findByRole("textbox", { name: "Редакционен фокус" });

    await user.click(screen.getByRole("button", { name: alternative }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/articles/${article.id}/focus`,
      expect.objectContaining({ method: "PUT" }),
    ));
    const focusWrites = fetchMock.mock.calls.filter(
      ([url, init]) => url.endsWith("/focus") && init?.method === "PUT",
    );
    // Exactly ONE save: the click is the save.
    expect(focusWrites).toHaveLength(1);
    expect(await screen.findByRole("textbox", { name: "Редакционен фокус" })).toHaveValue(alternative);
    expect(focus).toBeInTheDocument();
  });

  it("keeps the Focus freely editable and treats an empty one as the current blocker", async () => {
    // §11 + §35: free text still works, and the empty case keeps the ONE clear
    // blocker the backend sends.
    const empty = eligiblePreparation({
      preparation: {
        ...eligiblePreparation().preparation!,
        focusConfirmed: false,
        draftEligible: false,
        draftReadiness: {
          code: "FOCUS_NOT_CONFIRMED",
          message: "Добавете редакционен фокус, за да създадете чернова.",
        },
        availableActions: ["SELECT_FOCUS"],
      },
      availableActions: ["SELECT_FOCUS"],
    });
    renderArticle(empty);
    const focus = await screen.findByRole("textbox", { name: "Редакционен фокус" });
    expect(focus).toBeEnabled();
    expect(screen.getByText("Добавете редакционен фокус, за да създадете чернова.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Направи чернова" })).toBeNull();
  });

  it("keeps a route back to the originating Story", async () => {
    // §16: the editor can always return to the Story this Article came from.
    renderArticle(eligiblePreparation());
    const link = await screen.findByRole("link", { name: storyDetail.title });
    expect(link).toHaveAttribute("href", `/stories/${storyDetail.id}`);
  });

  it("names one research action and reuses the canonical Story command", async () => {
    // §21: «Проучи историята» issues the SAME canonical Story research command.
    const unassessed = eligiblePreparation({
      preparation: {
        ...eligiblePreparation().preparation!,
        draftEligible: false,
        draftReadiness: {
          code: "STORY_UNASSESSED",
          message: "За чернова първо е нужно проучване на историята.",
        },
        availableActions: ["CHANGE_FOCUS", "RESEARCH_MORE"],
      },
      availableActions: ["CHANGE_FOCUS", "RESEARCH_MORE"],
    });
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/research")) return dataResponse({ data: storyDetail });
      return dataResponse(unassessed);
    });
    const user = userEvent.setup();
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${unassessed.id}`] });

    await user.click(await screen.findByRole("button", { name: "Проучи историята" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/stories/${storyDetail.id}/research`,
      expect.objectContaining({ method: "POST" }),
    ));
  });
});

describe("V1.2-G3 §36 — the Draft is the centre of the screen", () => {
  it("offers exactly one body control and no duplicate save control", async () => {
    // §13: the C3 fix is preserved. The title moved to the header, so there is
    // still exactly ONE body textarea and still no Save button.
    //
    // V1.2-G4.3: a Draft is directly editable, so the editor is already open and
    // there is no `Редактирай` step to click through first.
    renderArticle(activeDraftArticle);

    expect(await screen.findByRole("textbox", { name: "Текст на статията" })).toBeInTheDocument();
    expect(document.querySelectorAll("textarea")).toHaveLength(1);
    expect(document.querySelectorAll("#article-working-body")).toHaveLength(1);
    // The labelled control is the one the label points at — no orphan.
    expect(document.querySelector('label[for="article-working-body"]')).not.toBeNull();
    const ids = Array.from(document.querySelectorAll("[id]")).map((node) => node.id);
    expect(new Set(ids).size).toBe(ids.length);
    // §14: no manual save anywhere.
    expect(screen.queryByRole("button", { name: /запази/i })).toBeNull();
  });

  it("opens a Draft ready to type, with no step in between", async () => {
    // V1.2-G4.3: Draft -> start writing. The extra `Редактирай` gate bought
    // nothing on a page that already autosaves and already negotiates a version.
    renderArticle(activeDraftArticle);
    expect(await screen.findByRole("textbox", { name: "Текст на статията" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Заглавие" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Редактирай" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Завърши редакцията" })).toBeNull();
  });

  it("keeps the title editable in the header and autosaves through the same writer", async () => {
    // §7/§8 + §14: the title is the h1, and it saves through the ONE autosave
    // that the body uses — one writer, one content version.
    const user = userEvent.setup();
    let canonical = activeDraftArticle;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) {
        const body = JSON.parse(String(init.body)) as { title: string; body: string; expectedVersion: number };
        canonical = {
          ...canonical,
          content: { title: body.title, body: body.body, version: body.expectedVersion + 1 },
        };
        return dataResponse(canonical);
      }
      return dataResponse(canonical);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeDraftArticle.id}`] });

    const title = await screen.findByRole("textbox", { name: "Заглавие" });
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toContainElement(title);

    await user.clear(title);
    await user.type(title, "Ремонтът на булевард „Свобода“ започва през октомври");
    await user.tab();

    await waitFor(() => expect(screen.getByText("Запазено")).toBeInTheDocument());
    // ONE content write carried BOTH fields, on one expectedVersion.
    const writes = fetchMock.mock.calls.filter(
      ([url, init]) => url.endsWith("/content") && init?.method === "PUT",
    );
    expect(writes.length).toBeGreaterThan(0);
    const last = JSON.parse(String((writes.at(-1)?.[1] as RequestInit).body)) as { title: string };
    expect(last.title).toBe("Ремонтът на булевард „Свобода“ започва през октомври");
  });

  it("shows the support rail only when the Article has evidence to support it with", async () => {
    // §6/§17: the rail is not reserved empty.
    const bare: ArticleDetail = {
      ...activeDraftArticle,
      factsAndSources: [],
      missingInformation: { items: [], assessedAt: "2026-09-25T09:32:00Z", evidenceStatus: "assessed" },
    };
    renderArticle(bare);
    await screen.findByRole("heading", { name: "Чернова" });
    expect(screen.queryByRole("heading", { name: "Факти и източници" })).toBeNull();
    expect(screen.queryByRole("button", { name: /източниците/ })).toBeNull();

    renderArticle(activeDraftArticle);
    expect(await screen.findByRole("heading", { name: "Факти и източници" })).toBeInTheDocument();
  });

  it("collapses the support rail and gives the writing surface the width back", async () => {
    // §19: one control, real expanded/collapsed state, no draggable pane.
    const user = userEvent.setup();
    renderArticle(activeDraftArticle);
    const toggle = await screen.findByRole("button", { name: "Скрий източниците" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", "article-evidence-body");
    await user.click(toggle);
    const collapsed = screen.getByRole("button", { name: "Покажи източниците" });
    expect(collapsed).toHaveAttribute("aria-expanded", "false");
    await user.click(collapsed);
    expect(screen.getByRole("button", { name: "Скрий източниците" })).toHaveAttribute("aria-expanded", "true");
  });

  it("names the opened publication a single-source Draft was written from", async () => {
    // V1.2-G4.3: the rail used to be headed «Факти и източници» while showing no
    // fact AND no source on a single-source Draft. The editor has to see which
    // page the text came from, and be able to open it.
    const singleSource: ArticleDetail = {
      ...activeDraftArticle,
      factsAndSources: [],
      missingInformation: {
        items: [],
        assessedAt: "2026-09-25T09:32:00Z",
        evidenceStatus: "assessed",
        openedSources: [
          {
            id: "chernomorski-far",
            name: "Черноморски фар",
            url: "https://www.faragency.bg/news/17905162794342/slab-start",
            domain: "faragency.bg",
            factualAuthority: false,
            authority: "CORROBORATING",
          },
        ],
      },
    };
    renderArticle(singleSource);
    expect(await screen.findByRole("heading", { name: "Изходен материал" })).toBeInTheDocument();

    const origin = document.querySelector("[data-article-origin]") as HTMLAnchorElement;
    expect(origin).not.toBeNull();
    expect(origin).toHaveAttribute("href", singleSource.missingInformation.openedSources![0]!.url);
    expect(origin).toHaveAttribute("target", "_blank");
    expect(origin).toHaveAttribute("rel", expect.stringContaining("noreferrer") as unknown as string);

    // The honest count: one opened page is not corroboration.
    expect(screen.getByText(/Един източник · няма независимо потвърждение/)).toBeVisible();
  });

  it("keeps the rail reserved-empty only when there is genuinely nothing", async () => {
    // An opened publication alone is enough for the rail to exist: it is the
    // material behind the Draft even when no fact was promoted.
    const openedOnly: ArticleDetail = {
      ...activeDraftArticle,
      factsAndSources: [],
      missingInformation: {
        ...activeDraftArticle.missingInformation,
        items: [],
        openedSources: [
          {
            id: "far",
            name: "Черноморски фар",
            url: "https://www.faragency.bg/news/x",
            domain: "faragency.bg",
            factualAuthority: false,
            authority: "CORROBORATING",
          },
        ],
      },
    };
    renderArticle(openedOnly);
    expect(await screen.findByRole("heading", { name: "Факти и източници" })).toBeInTheDocument();
  });

  it("keeps publications and evidence as two different things", async () => {
    // §17/§36: the rail is this Article's factual support. It never becomes a
    // list of incoming publications and never implies verification.
    renderArticle(activeDraftArticle);
    await screen.findByRole("heading", { name: "Факти и източници" });
    const body = document.body.textContent ?? "";
    for (const forbidden of ["Публикации", "EvidencePacket", "authority", "claim", "provenance"]) {
      expect(body).not.toContain(forbidden);
    }
  });

  it("attaches a warning to the decision it affects instead of one large panel", async () => {
    // §20: the warning sits with the readiness block, in the frozen severity
    // hierarchy, and is not hidden behind a modal.
    const warning = {
      id: "warn_review_1",
      severity: "review" as const,
      message: "Има твърдение, което изисква проверка.",
      affectedText: "Във вътрешния двор се събраха граждани, които питат за съдбата на пазара.",
      blocking: false,
    };
    renderArticle({ ...activeDraftArticle, warnings: [warning] });
    expect(await screen.findByRole("heading", { name: "Какво да прегледаш" })).toBeInTheDocument();
    expect(screen.getByText(warning.message)).toBeVisible();
    expect(screen.getByText(warning.affectedText)).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers the Mark Ready decision only from the backend's own action", async () => {
    // §25: readiness is never automatic and never granted by React.
    renderArticle({ ...activeDraftArticle, availableActions: ["EDIT"] });
    await screen.findByRole("heading", { name: "Чернова" });
    expect(screen.queryByRole("button", { name: "Отбележи като готова" })).toBeNull();
  });

  it("marks the Draft Ready through the canonical command", async () => {
    const user = userEvent.setup();
    // The canonical projection is tracked across the refetch: a state that only
    // lives in the mutation response would be a local guess, not a product fact.
    let canonical: ArticleDetail = activeDraftArticle;
    const ready = { ...activeReadyArticle, id: activeDraftArticle.id, story: activeDraftArticle.story };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/ready")) {
        canonical = ready;
        return dataResponse(ready);
      }
      return dataResponse(canonical);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeDraftArticle.id}`] });
    await user.click(await screen.findByRole("button", { name: "Отбележи като готова" }));
    expect(await screen.findByText("Готова")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url, init]) => url.endsWith("/ready") && init?.method === "POST");
    expect(call).toBeDefined();
  });
});

describe("V1.2-G3 §37 — Ready and Finalized", () => {
  it("shows exactly one forward action on a Ready Article", async () => {
    // §26/§29: «Финализирай» leads, «Редактирай» is the quiet alternative.
    renderArticle(activeReadyArticle);
    await screen.findByText("Готова");
    const finalize = screen.getByRole("button", { name: "Финализирай" });
    const edit = screen.getByRole("button", { name: "Редактирай" });
    expect(finalize.className).not.toBe(edit.className);
    expect(screen.queryByRole("button", { name: "Отбележи като готова" })).toBeNull();
  });

  it("returns a Ready Article to Draft through the canonical reopen command", async () => {
    // §26: Ready -> Edit -> Draft, with no confirmation dialog for reopening.
    const user = userEvent.setup();
    let canonical: ArticleDetail = activeReadyArticle;
    const reopened: ArticleDetail = {
      ...activeDraftArticle,
      id: activeReadyArticle.id,
      story: activeReadyArticle.story,
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/reopen")) {
        canonical = reopened;
        return dataResponse(reopened);
      }
      return dataResponse(canonical);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeReadyArticle.id}`] });
    await user.click(await screen.findByRole("button", { name: "Редактирай" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/articles/${activeReadyArticle.id}/reopen`,
      expect.objectContaining({ method: "POST" }),
    ));
    expect(await screen.findByRole("heading", { name: "Чернова" })).toBeInTheDocument();
  });

  it("finalizes through the canonical API and lands in the Archive", async () => {
    // §27: the last editorial step, not publication.
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/finalize")) {
        return dataResponse({
          articleId: activeReadyArticle.id,
          archivePath: `/archive/${activeReadyArticle.id}`,
          finalizedAt: "2026-09-26T10:00:00Z",
          article: { ...activeReadyArticle, state: null, isFinalized: true },
        });
      }
      return dataResponse(activeReadyArticle);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeReadyArticle.id}`] });
    await user.click(await screen.findByRole("button", { name: "Финализирай" }));
    expect(await screen.findByText("Архивна статия")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url, init]) => url.endsWith("/finalize") && init?.method === "POST");
    expect(call).toBeDefined();
  });

  it("never speaks of publishing, anywhere on the Article", async () => {
    // §27/§28/§37: `Публикувай` does not exist in this product, and finalized
    // is not published.
    for (const article of [activePreparationArticle, activeDraftArticle, activeReadyArticle]) {
      renderArticle(article);
      await screen.findAllByRole("heading", { level: 1 });
      const body = document.body.textContent ?? "";
      for (const forbidden of ["Публикувай", "Публикува", "Изпрати", "Одобри", "CMS", "Експорт"]) {
        expect(body).not.toContain(forbidden);
      }
    }
  });

  it("keeps manual continuation a normal writing session after a real failure", async () => {
    // §15: the recovery path must not look like an error mode.
    const user = userEvent.setup();
    let canonical: ArticleDetail = failedPreparationArticle;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) {
        const body = JSON.parse(String(init.body)) as { title: string; body: string; expectedVersion: number };
        canonical = {
          ...activeDraftArticle,
          id: failedPreparationArticle.id,
          story: failedPreparationArticle.story,
          content: { title: body.title, body: body.body, version: body.expectedVersion + 1 },
        };
        return dataResponse(canonical);
      }
      return dataResponse(canonical);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${failedPreparationArticle.id}`] });
    await user.click(await screen.findByRole("button", { name: "Редактирай" }));

    // A normal title field and one body control, then the same canonical Draft.
    const body = screen.getByRole("textbox", { name: "Текст на статията" });
    await user.type(body, "Черновата не беше генерирана автоматично, но е написана.");
    await user.tab();
    expect(await screen.findByRole("heading", { name: "Чернова" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([url, init]) => !(url.endsWith("/draft") && init?.method === "POST"))).toBe(true);
  });

  it("never invents an Article state beyond the three canonical ones", async () => {
    // §31: transient operations are not persistent states.
    const vocabulary = ["Проучва се", "Генерира се", "Има грешка", "Проверка"];
    renderArticle(activeDraftArticle);
    await screen.findByRole("heading", { name: "Чернова" });
    const body = document.body.textContent ?? "";
    for (const forbidden of vocabulary) {
      expect(body).not.toContain(forbidden);
    }
  });

  it("reports a failed autosave truthfully without exposing internals", async () => {
    // §8: a passive, honest save state — no version, no concurrency id, no API
    // error vocabulary.
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/content")) {
        return errorResponse("INTERNAL_ERROR", "Записът не е завършен.", 500);
      }
      return dataResponse(activeDraftArticle);
    });
    renderWithProviders(articleRoute(), { initialEntries: [`/articles/${activeDraftArticle.id}`] });
    const body = await screen.findByRole("textbox", { name: "Текст на статията" });
    const typed = "Текст, който няма да се запише.";
    await user.clear(body);
    await user.type(body, typed);
    await user.tab();

    expect(await screen.findByText("Неуспешно запазване")).toBeInTheDocument();
    // The editor's own text is not thrown away by a failed save.
    expect(screen.getByRole("textbox", { name: "Текст на статията" })).toHaveValue(typed);
    // A retry is offered, and it is not a second save control on the page.
    expect(screen.getByRole("button", { name: "Опитайте отново" })).toBeInTheDocument();
  });
});
