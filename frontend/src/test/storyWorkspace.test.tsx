import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StoryDetail } from "../api/dto";
import { StoryWorkspace } from "../pages/StoryWorkspace";
import { storyDetail } from "./fixtures";
import { renderWithProviders } from "./render";
import {
  PUBLICATIONS_PREVIEW,
  headerPrimaryAction,
  isResearchForward,
  orderPublications,
} from "../pages/story/storyView";

/**
 * V1.2-G2 §35: the Story workspace proof.
 *
 * Every test here exists because this slice could plausibly have gone the other
 * way — a plausible panel grid, a plausible reassuring sentence for an empty
 * evidence basis, a plausible trust badge — and these are the assertions that
 * make the *honest* version fail if it is undone.
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

function storyRoute() {
  return (
    <Routes>
      <Route path="/stories/:storyId" element={<StoryWorkspace />} />
      <Route path="/articles/:articleId" element={<p>Работа за статия</p>} />
      <Route path="/archive/:articleId" element={<p>Архив</p>} />
    </Routes>
  );
}

function renderStory(detail: StoryDetail) {
  return renderWithProviders(storyRoute(), {
    initialEntries: [`/stories/${detail.id}`],
  });
}

/** One always-stories backend, so a test only has to name the method it cares about. */
function storyOnly(detail: StoryDetail) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") {
      return dataResponse(detail);
    }
    if (url.includes(`/api/v1/stories/${detail.id}`)) return dataResponse(detail);
    throw new Error(`Unexpected URL ${url}`);
  });
}

/** The unassessed Story of §9/§27: nothing researched, three publications. */
const unassessedStory: StoryDetail = {
  ...storyDetail,
  id: "s-unassessed",
  title: "Община Несебър започва ремонта на крайбрежната алея",
  summary: "",
  whatHappened: "",
  reviewed: false,
  followed: false,
  publisherCount: 3,
  availableActions: ["REVIEW", "FOLLOW", "IGNORE", "RESEARCH_MORE", "START_ARTICLE"],
  unreviewedDevelopmentCount: 0,
  newDevelopments: [],
  chronology: [],
  relatedArticles: [],
  factsAndSources: [],
  missingInformation: { items: [], assessedAt: null, evidenceStatus: "unassessed" },
  correction: { available: false, actions: [] },
};

/** The assessed Story of §36-B: confirmed facts, their sources, no gaps. */
const assessedStory: StoryDetail = {
  ...storyDetail,
  id: "s-assessed",
  title: "Община Несебър започва ремонта на крайбрежната алея",
  summary: "",
  whatHappened:
    "Общината обяви началото на ремонта на крайбрежната алея през следващата седмица.",
  reviewed: true,
  publisherCount: 3,
  availableActions: ["UNFOLLOW", "IGNORE", "START_ARTICLE"],
  relatedArticles: [
    { id: "a-nesebar", title: "Ремонтът на алеята започва през октомври", state: "draft" },
  ],
  factsAndSources: [
    {
      id: "f-1",
      text: "Община Несебър започва ремонта на крайбрежната алея през следващата седмица.",
      source: { id: "bnr", name: "БНР", url: "https://bnr.example.test/nesebar-aleya" },
      scope: "current",
    },
    {
      id: "f-2",
      text: "Ремонтът обхваща около 1,2 км.",
      source: { id: "vestnik", name: "Вестник", url: "https://vestnik.example.test/aleya" },
      scope: "current",
    },
  ],
  missingInformation: { items: [], assessedAt: "2026-09-25T09:32:00Z", evidenceStatus: "assessed" },
  newDevelopments: [],
  chronology: [],
  correction: { available: false, actions: [] },
};

/** A Story with twelve grouped publications and only two opened sources (§36-D). */
const manyPublications: StoryDetail = {
  ...assessedStory,
  id: "s-manyPublications",
  publications: Array.from({ length: 12 }, (_, index) => ({
    id: `pub-${index}`,
    title: `Публикация ${index + 1}`,
    source: { id: `src-${index}`, name: `Издателство ${index + 1}` },
    url: `https://example.test/${index}`,
    publishedAt: `2026-09-${String(25 - index).padStart(2, "0")}T08:00:00Z`,
    discoveredAt: `2026-09-${String(25 - index).padStart(2, "0")}T09:00:00Z`,
    summary: "",
    factsAndSourceIds: [],
  })),
};

describe("V1.2-G2 — unassessed Story", () => {
  it("renders one honest empty state instead of three empty panels", async () => {
    storyOnly(unassessedStory);
    renderStory(unassessedStory);
    await screen.findByRole("heading", { level: 1, name: unassessedStory.title });

    expect(screen.getByText("Историята още не е проучена.")).toBeVisible();
    // §9: no empty Facts, no empty Sources, no empty Missing Information.
    expect(screen.queryByRole("heading", { name: "Факти и източници" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Какво липсва" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Статии" })).toBeNull();
    // §9/§27: a never-assessed basis is never dressed up as a clean one.
    for (const forbidden of ["Няма отбелязани липси", "Няма налични факти", "Няма липси"]) {
      expect(document.body.textContent).not.toContain(forbidden);
    }
    // §15: the action that changes this state is on the page.
    expect(screen.getByRole("button", { name: "Проучи още" })).toBeEnabled();
  });

  it("keeps the unassessed sentence out of an assessed, gapless Story", async () => {
    storyOnly(assessedStory);
    renderStory(assessedStory);
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });

    // §9: "assessed, no gaps" renders neither the unassessed state nor
    // "Какво липсва: Няма".
    expect(screen.queryByText("Историята още не е проучена.")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Какво липсва" })).toBeNull();
  });
});

describe("V1.2-G2 — facts and sources", () => {
  it("renders each confirmed fact with the source that supports it", async () => {
    storyOnly(assessedStory);
    renderStory(assessedStory);
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });

    const block = screen.getByRole("heading", { name: "Факти и източници" }).closest("section")!;
    for (const fact of assessedStory.factsAndSources) {
      const item = within(block).getByText(fact.text).closest("li")!;
      // §10: the source visibly belongs to the fact it supports.
      expect(within(item).getByRole("link", { name: fact.source.name })).toHaveAttribute(
        "href",
        fact.source.url,
      );
    }
    // §13: a real opened source opens in a new tab, safely.
    const link = within(block).getByRole("link", { name: "БНР" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noreferrer");
  });

  it("shows no internal identifiers, locators or trust labels", async () => {
    storyOnly(assessedStory);
    renderStory(assessedStory);
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });

    const text = document.body.textContent ?? "";
    for (const forbidden of [
      "Надежден",
      "Ненадежден",
      "Verified",
      "Trusted",
      "source tier",
      "факт-",
      "f-1",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });
});

describe("V1.2-G2 — what is missing", () => {
  const blocking: StoryDetail = {
    ...assessedStory,
    id: "s-blocking",
    availableActions: ["UNFOLLOW", "IGNORE", "RESEARCH_MORE", "START_ARTICLE"],
    missingInformation: {
      items: [
        { id: "gap-1", question: "Кога точно започва ремонтът?", kind: "missing_fact", blocking: true },
        { id: "gap-2", question: "Ще има ли компенсация за жителите?", kind: "unresolved", blocking: false },
      ],
      assessedAt: "2026-09-25T09:32:00Z",
      evidenceStatus: "assessed",
    },
  };

  it("shows a real gap with the plain word for a blocking one and no enum", async () => {
    storyOnly(blocking);
    renderStory(blocking);
    await screen.findByRole("heading", { level: 1, name: blocking.title });

    expect(screen.getByRole("heading", { name: "Какво липсва" })).toBeVisible();
    expect(screen.getByText("Кога точно започва ремонтът?")).toBeVisible();
    // §14: the internal classification is never shown to the editor.
    expect(document.body.textContent).not.toContain("BLOCKING_GAP");
    expect(document.body.textContent).toContain("пречи");
  });

  it("keeps a non-blocking gap neutral", async () => {
    storyOnly(blocking);
    renderStory(blocking);
    await screen.findByRole("heading", { level: 1, name: blocking.title });

    const section = screen.getByRole("heading", { name: "Какво липсва" }).closest("section")!;
    const rows = [...section.querySelectorAll("li")];
    const blockingRow = rows.find((row) => row.textContent?.includes("Кога точно"))!;
    const neutralRow = rows.find((row) => row.textContent?.includes("компенсация"))!;

    // A distinct treatment exists for the blocking gap and not for the other.
    const blockingClass = blockingRow.className;
    const neutralClass = neutralRow.className;
    expect(blockingClass).not.toBe(neutralClass);
    expect(blockingClass).toMatch(/gapBlocking/);
    expect(blockingRow.className).not.toMatch(/_error|red/i);
  });

  it("offers research only when the backend offers it", async () => {
    storyOnly(assessedStory);
    renderStory(assessedStory);
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });
    // The assessed Story has no gaps, so the backend withholds RESEARCH_MORE
    // and the page must not invent the action (§5/§15).
    expect(screen.queryByRole("button", { name: "Проучи още" })).toBeNull();

    fetchMock.mockReset();
    storyOnly(blocking);
    renderStory(blocking);
    expect(await screen.findByRole("button", { name: "Проучи още" })).toBeEnabled();
  });
});

describe("V1.2-G2 — research interaction", () => {
  const gapStory: StoryDetail = {
    ...assessedStory,
    id: "s-research",
    availableActions: ["UNFOLLOW", "RESEARCH_MORE", "START_ARTICLE"],
    missingInformation: {
      items: [{ id: "gap-1", question: "Кога точно започва ремонтът?", kind: "missing_fact", blocking: true }],
      assessedAt: "2026-09-25T09:32:00Z",
      evidenceStatus: "assessed",
    },
  };

  it("shows one calm pending status and no stage vocabulary", async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-g2" } }) } as Response;
      }
      if (_url.includes("/operations/op-g2")) return pending;
      return dataResponse(gapStory);
    });
    const user = userEvent.setup();
    renderStory(gapStory);
    await screen.findByRole("heading", { level: 1, name: gapStory.title });

    await user.click(screen.getByRole("button", { name: "Проучи още" }));

    // §16: one status sentence, and none of the machinery behind it.
    const status = await screen.findByText("Проучва се…");
    expect(status).toBeDisabled();
    const pendingRegion = document.querySelector("[data-research-trigger]")!;
    for (const stage of ["търсене", "отваряне", "проверка", "модел", "пакет", "provider"]) {
      expect(pendingRegion.textContent?.toLowerCase()).not.toContain(stage);
    }
    release(dataResponse({ status: "succeeded", result: { status: "succeeded" } }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Проучи още" })).toBeEnabled(),
    );
  });

  it("keeps the confirmed facts and gaps when a round fails", async () => {
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return { ok: true, status: 202, json: async () => ({ data: { operationToken: "op-fail" } }) } as Response;
      }
      if (_url.includes("/operations/op-fail")) {
        return { ok: true, status: 200, json: async () => ({ data: { status: "FAILED", error: { code: "SOURCE_UNAVAILABLE", message: "Източникът не можа да бъде отворен. Опитайте отново." } } }) } as Response;
      }
      return dataResponse(gapStory);
    });
    const user = userEvent.setup();
    renderStory(gapStory);
    await screen.findByRole("heading", { level: 1, name: gapStory.title });

    await user.click(screen.getByRole("button", { name: "Проучи още" }));

    // §17: the backend's own sentence, beside the gaps it is about.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Източникът не можа да бъде отворен. Опитайте отново.");
    // ... and a failure erases neither the facts nor the gaps.
    expect(screen.getByText(assessedStory.factsAndSources[0]!.text)).toBeVisible();
    expect(screen.getByText("Кога точно започва ремонтът?")).toBeVisible();
    // §17: no invented reputation judgement.
    expect(document.body.textContent).not.toMatch(/надежден/i);
  });
});

describe("V1.2-G2 — publications versus evidence", () => {
  it("lists member publications separately from the confirmed sources", async () => {
    storyOnly(manyPublications);
    renderStory(manyPublications);
    await screen.findByRole("heading", { level: 1, name: manyPublications.title });

    const evidence = screen.getByRole("heading", { name: "Факти и източници" }).closest("section")!;
    const publications = screen.getByRole("heading", { name: "Публикации" }).closest("section")!;

    // §18: a grouped publication is not evidence. The twelve publications are
    // not dressed up as confirmed sources anywhere.
    expect(within(evidence).queryByText("Публикация 1")).toBeNull();
    expect(within(publications).queryByText(assessedStory.factsAndSources[0]!.text)).toBeNull();
    // Only the two opened sources appear under the facts.
    expect(within(evidence).getByText("БНР")).toBeVisible();
  });

  it("keeps a long Story usable with a compact list and one expander", async () => {
    const user = userEvent.setup();
    storyOnly(manyPublications);
    renderStory(manyPublications);
    await screen.findByRole("heading", { level: 1, name: manyPublications.title });

    const publications = screen.getByRole("heading", { name: "Публикации" }).closest("section")!;
    expect(within(publications).getAllByRole("listitem")).toHaveLength(PUBLICATIONS_PREVIEW);

    const expander = within(publications).getByRole("button", { name: "Покажи всички 12 публикации" });
    await user.click(expander);

    expect(within(publications).getAllByRole("listitem")).toHaveLength(12);
    // Newest first: a view preference, not a new projection.
    expect(within(publications).getAllByRole("listitem")[0]).toHaveTextContent("Публикация 1");
  });
});

describe("V1.2-G2 — article relationship", () => {
  it("summarises the Story's Article and links to its workspace", async () => {
    storyOnly(assessedStory);
    renderStory(assessedStory);
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });

    const section = screen.getByRole("heading", { name: "Статии" }).closest("section")!;
    expect(within(section).getByText("Чернова")).toBeVisible();
    expect(within(section).getByRole("link", { name: "Отвори" })).toHaveAttribute(
      "href",
      "/articles/a-nesebar",
    );
    // §22: the Article editor is not duplicated here.
    expect(within(section).queryByRole("textbox")).toBeNull();
  });

  it("shows several Articles without choosing one for the editor", async () => {
    const several: StoryDetail = {
      ...assessedStory,
      relatedArticles: [
        { id: "a-1", title: "Първа статия", state: "preparation" },
        { id: "a-2", title: "Втора статия", state: "ready" },
        { id: "a-3", title: "Трета статия", finalizedAt: "2026-09-24T10:00:00Z" },
      ],
    };
    storyOnly(several);
    renderStory(several);
    await screen.findByRole("heading", { level: 1, name: several.title });

    const section = screen.getByRole("heading", { name: "Статии" }).closest("section")!;
    expect(within(section).getAllByRole("listitem")).toHaveLength(3);
    // Nothing is marked primary, and a finalized Article is not in a state.
    expect(within(section).getByText("Подготовка")).toBeVisible();
    expect(within(section).getByText("Готова")).toBeVisible();
    expect(within(section).getByText("В архива")).toBeVisible();
    expect(within(section).getAllByRole("link", { name: "Отвори" })[0]).toHaveAttribute(
      "href",
      "/articles/a-1",
    );
    expect(within(section).queryByText(/основна|главна/i)).toBeNull();
  });

  it("renders no Article panel when there is no Article", async () => {
    storyOnly({ ...assessedStory, relatedArticles: [] });
    renderStory({ ...assessedStory, relatedArticles: [] });
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });
    // §24: only the action, never an empty panel.
    expect(screen.queryByRole("heading", { name: "Статии" })).toBeNull();
    expect(screen.getByRole("button", { name: "Започни статия" })).toBeVisible();
  });
});

describe("V1.2-G2 — honesty of the page", () => {
  it("invents no category, locality or importance", async () => {
    const local: StoryDetail = {
      ...assessedStory,
      title: "Община Несебър затвори площадка за ремонт",
    };
    storyOnly(local);
    renderStory(local);
    await screen.findByRole("heading", { level: 1, name: local.title });

    const header = document.querySelector("header")!;
    // §3/§31: only backend-backed metadata, and never a locality read out of
    // the headline, a category badge, a score or an importance marker. The
    // place name exists in the headline, which is the backend's own text; what
    // must not exist is a *derived* locality in the metadata line.
    expect(header.textContent).toContain("Прегледана:");
    const metadata = document.querySelector("[class*='meta']")!;
    expect(metadata.textContent).not.toContain("Несебър");
    for (const forbidden of ["категория", "重要性", "оценка", "score", "важност"]) {
      expect(document.body.textContent?.toLowerCase()).not.toContain(forbidden);
    }
  });

  it("uses no technical vocabulary", async () => {
    storyOnly(assessedStory);
    renderStory(assessedStory);
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });

    const text = (document.body.textContent ?? "").toLowerCase();
    for (const forbidden of [
      "evidencepacket",
      "provenance",
      "модел",
      "доставчик",
      "authority",
      "операция ",
      "endpoint",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("keeps the grouping correction collapsed, quiet and backend-driven", async () => {
    // §25: rendered only when the projection offers it, at the foot of the page.
    const corrected: StoryDetail = {
      ...assessedStory,
      correction: { available: true, actions: ["DETACH_PUBLICATION", "MERGE_STORY"] },
    };
    storyOnly(corrected);
    const { unmount } = renderStory(corrected);
    await screen.findByRole("heading", { level: 1, name: corrected.title });

    const toggle = screen.getByRole("button", { name: /Корекция на групирането/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // No destructive emphasis.
    expect(toggle.className).not.toMatch(/error|destructive/);
    // And it is last on the page, after the editorial content.
    const page = document.body.textContent ?? "";
    expect(page.indexOf("Корекция на групирането")).toBeGreaterThan(page.indexOf("Публикации"));

    // The backend offers nothing on a normal Story, so nothing is rendered.
    unmount();
    fetchMock.mockReset();
    storyOnly(assessedStory);
    renderStory(assessedStory);
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });
    expect(screen.queryByRole("button", { name: /Корекция на групирането/ })).toBeNull();
  });

  it("offers a quiet way back to Истории", async () => {
    storyOnly(assessedStory);
    renderStory(assessedStory);
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });
    expect(screen.getByRole("link", { name: "← Истории" })).toHaveAttribute("href", "/stories");
  });

  it("keeps the follow control quiet and separate from the forward action", async () => {
    storyOnly({ ...assessedStory, relatedArticles: [], availableActions: ["UNFOLLOW", "IGNORE", "START_ARTICLE"] });
    renderStory({ ...assessedStory, relatedArticles: [], availableActions: ["UNFOLLOW", "IGNORE", "START_ARTICLE"] });
    await screen.findByRole("heading", { level: 1, name: assessedStory.title });

    const start = screen.getByRole("button", { name: "Започни статия" });
    const unfollow = screen.getByRole("button", { name: "Спри следването" });
    // §7/§29: one filled control, and following is not one of them.
    expect(start.className).toMatch(/_primary_/);
    expect(unfollow.className).toMatch(/_quiet_/);
    expect(unfollow.className).not.toMatch(/_primary_/);
  });

  it("shows exactly one filled control on the page", async () => {
    const rich: StoryDetail = {
      ...assessedStory,
      id: "s-rich",
      availableActions: ["REVIEW", "FOLLOW", "IGNORE", "RESEARCH_MORE", "START_ARTICLE"],
      relatedArticles: [],
      missingInformation: {
        items: [{ id: "gap-1", question: "Кога започва ремонтът?", kind: "missing_fact", blocking: true }],
        assessedAt: "2026-09-25T09:32:00Z",
        evidenceStatus: "assessed",
      },
    };
    storyOnly(rich);
    renderStory(rich);
    await screen.findByRole("heading", { level: 1, name: rich.title });

    const filled = [...document.querySelectorAll("button")].filter((button) =>
      button.className.includes("_primary_"),
    );
    expect(filled).toHaveLength(1);
    expect(filled[0]).toHaveTextContent("Проучи още");
    // §15/§29: the filled control sits with the gaps, not in a row of equals.
    expect(headerPrimaryAction(rich)).toBeNull();
    expect(isResearchForward(rich)).toBe(true);
  });

  it("orders publications newest first without mutating the payload", () => {
    const rows = manyPublications.publications;
    const snapshot = rows.map((row) => row.id);
    const ordered = orderPublications(rows);
    expect(ordered[0]!.id).toBe("pub-0");
    expect(rows.map((row) => row.id)).toEqual(snapshot);
  });
});
