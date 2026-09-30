import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HintSeedControl } from "../pages/HintSeedControl";
import { renderWithProviders } from "./render";

/**
 * V1.2-G4.20 — «Започни от идея».
 *
 * The backend promise is that the hint is a search query and never evidence.
 * These tests hold the UI to the matching promise: it may not imply that the
 * editor's words became an article, and it may not turn "found nothing" into
 * a system failure. The report is the part that matters — an editor who
 * cannot distinguish zero-found from broken cannot decide what to do next.
 */

const seedStoriesFromHint = vi.fn();

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, seedStoriesFromHint: (hint: string) => seedStoriesFromHint(hint) };
});

beforeEach(() => {
  seedStoriesFromHint.mockReset();
});

describe("Започни от идея", () => {
  it("stays collapsed until the editor asks for it", () => {
    renderWithProviders(<HintSeedControl />);
    expect(screen.getByTestId("hint-seed-open")).toBeTruthy();
    expect(screen.queryByTestId("hint-seed-panel")).toBeNull();
  });

  it("opens a hint field and refuses to search a fragment", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HintSeedControl />);
    await user.click(screen.getByTestId("hint-seed-open"));
    expect(screen.getByTestId("hint-seed-panel")).toBeTruthy();
    // The server's own minimum is 6 characters; the button mirrors it so the
    // editor is not sent on a round trip that cannot succeed.
    await user.type(screen.getByLabelText(/темата/i), "ЦИК");
    expect(screen.getByTestId("hint-seed-run")).toHaveProperty("disabled", true);
  });

  it("sends the editor's hint and reports the pages that really opened", async () => {
    const user = userEvent.setup();
    seedStoriesFromHint.mockResolvedValue({
      hint: "проверка на машините",
      opened: [{ title: "ЦИК", url: "https://cik.bg/news/2026/machines", itemId: "i-1", storyId: "s-1" }],
      openedCount: 1,
      considered: 1,
      unopened: [],
      providerChain: ["tinyfish"],
      searchStatus: "SEARCH_COMPLETE",
    });
    renderWithProviders(<HintSeedControl />);
    await user.click(screen.getByTestId("hint-seed-open"));
    await user.type(screen.getByLabelText(/темата/i), "проверка на машините");
    await user.click(screen.getByTestId("hint-seed-run"));
    await waitFor(() => expect(seedStoriesFromHint).toHaveBeenCalledWith("проверка на машините"));
    expect(await screen.findByTestId("hint-seed-report")).toHaveTextContent("Отворени са 1");
  });

  it("says zero when nothing opened, and does not call it a failure", async () => {
    const user = userEvent.setup();
    seedStoriesFromHint.mockResolvedValue({
      hint: "тема без резултат",
      opened: [],
      openedCount: 0,
      considered: 0,
      unopened: [],
      providerChain: ["tinyfish"],
      searchStatus: "NO_RESULTS",
    });
    renderWithProviders(<HintSeedControl />);
    await user.click(screen.getByTestId("hint-seed-open"));
    await user.type(screen.getByLabelText(/темата/i), "тема без резултат");
    await user.click(screen.getByTestId("hint-seed-run"));
    const report = await screen.findByTestId("hint-seed-report");
    expect(report).toHaveTextContent("Не се отвори нито една страница");
    // A zero is an answer about the world. It must not borrow the language of
    // a broken system, and it must not show an error banner.
    expect(screen.queryByTestId("hint-seed-error")).toBeNull();
  });

  it("names a page that would not open with its own category", async () => {
    const user = userEvent.setup();
    seedStoriesFromHint.mockResolvedValue({
      hint: "проверка на машините",
      opened: [],
      openedCount: 0,
      considered: 1,
      unopened: [
        { url: "https://example.org/a", status: "FETCH_TIMEOUT", detail: "connected but no body" },
      ],
      providerChain: ["tinyfish"],
      searchStatus: "SEARCH_COMPLETE",
    });
    renderWithProviders(<HintSeedControl />);
    await user.click(screen.getByTestId("hint-seed-open"));
    await user.type(screen.getByLabelText(/темата/i), "проверка на машините");
    await user.click(screen.getByTestId("hint-seed-run"));
    // A timeout must be visible as a timeout. Folding it into "no such
    // material exists" would send the editor off to change a topic that is
    // perfectly findable.
    const failures = await screen.findByTestId("hint-seed-failures");
    expect(failures).toHaveTextContent("FETCH_TIMEOUT");
  });

  it("keeps the report on screen and links the new story from it", async () => {
    const user = userEvent.setup();
    seedStoriesFromHint.mockResolvedValue({
      hint: "проверка на машините",
      opened: [{ title: "ЦИК", url: "https://cik.bg/", itemId: "i-1", storyId: "s-9" }],
      openedCount: 1,
      considered: 1,
      unopened: [],
      providerChain: ["tinyfish"],
      searchStatus: "SEARCH_COMPLETE",
    });
    renderWithProviders(<HintSeedControl />);
    await user.click(screen.getByTestId("hint-seed-open"));
    await user.type(screen.getByLabelText(/темата/i), "проверка на машините");
    await user.click(screen.getByTestId("hint-seed-run"));

    // The report must survive the request. An earlier version navigated to the
    // new story on success, which unmounted this component before the sentence
    // could be read: the editor was told pages were found by code that then
    // removed the news of it.
    expect(await screen.findByTestId("hint-seed-report")).toBeTruthy();
    // And the link must carry a STORY id, not the raw inbox item id, because
    // /stories/:id answers «Невалиден Story.» for the latter.
    const link = screen.getByRole("link", { name: "ЦИК" });
    expect(link.getAttribute("href")).toBe("/stories/s-9");
  });

  it("shows the server's own refusal rather than a generic one", async () => {
    const user = userEvent.setup();
    seedStoriesFromHint.mockRejectedValue(new Error("Подсказката е твърде кратка (3 символа)"));
    renderWithProviders(<HintSeedControl />);
    await user.click(screen.getByTestId("hint-seed-open"));
    await user.type(screen.getByLabelText(/темата/i), "проверка");
    await user.click(screen.getByTestId("hint-seed-run"));
    expect(await screen.findByTestId("hint-seed-error")).toHaveTextContent("твърде кратка");
  });
});
