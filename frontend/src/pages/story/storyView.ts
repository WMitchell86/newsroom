/**
 * V1.2-G2: the pure view logic behind the Story workspace.
 *
 * The Story page is a reading page, and the decisions that shape it are small
 * enough to state outright. They live here, away from the markup, because each
 * of them is a place where this slice could quietly start inventing product
 * state. The rules:
 *
 *   * **Absence is rendered as absence.** A section with no meaningful content
 *     is not rendered. "No facts" on an unassessed Story is *not* the same claim
 *     as "clean evidence", and the page never prints one in place of the other.
 *   * **Nothing is derived from a headline.** No locality, no category, no
 *     importance, no score. If the backend did not send it, the page has no way
 *     to know it.
 *   * **Publication order is a view preference.** The list is sorted newest
 *     first over rows the server already delivered, and the input array is never
 *     mutated.
 *   * **The backend offers the actions.** This module picks which offered
 *     action is *visually* primary; it never invents one, and it never widens
 *     the set.
 */

import type { ArticleState, Publication, StoryDetail } from "../../api/dto";

/**
 * §19: how many member publications are useful before the page offers the rest.
 *
 * A Story with seventeen grouped publications must not push the confirmed facts
 * off the screen. Five is a working set; the remainder stays one click away
 * because it is already in the payload — no new pagination, no new endpoint.
 */
export const PUBLICATIONS_PREVIEW = 5;

/** §27: the two visually different Story states, straight from the projection. */
export function isUnassessed(story: StoryDetail): boolean {
  return story.missingInformation?.evidenceStatus === "unassessed";
}

/**
 * §9: the real gaps. An empty list is an empty list — the page must not turn it
 * into a reassuring sentence.
 */
export function realGaps(story: StoryDetail): StoryDetail["missingInformation"]["items"] {
  return story.missingInformation?.items ?? [];
}

/**
 * §10/§27: the confirmed facts. Empty means "nothing confirmed", and on an
 * unassessed Story it means "nobody has looked yet".
 */
export function confirmedFacts(story: StoryDetail): StoryDetail["factsAndSources"] {
  return story.factsAndSources ?? [];
}

/**
 * §9: whether the page has anything to show under the evidence heading. A Story
 * with neither facts nor gaps renders no evidence block at all.
 */
export function hasEvidenceBasis(story: StoryDetail): boolean {
  return confirmedFacts(story).length > 0;
}

/**
 * §21: which member publications the backend classified as a new development.
 *
 * Taken from `newDevelopments` — the canonical, meaningful developments — and
 * used only to label a row. React never classifies a publication itself.
 */
export function developmentPublicationIds(story: StoryDetail): Set<string> {
  return new Set(story.newDevelopments.map((item) => item.publicationId));
}

/**
 * §19/§20: newest first, with the discovery timestamp as the fallback for a
 * publication whose feed carried none. A stable id tie-break keeps equal
 * timestamps in the order the server delivered.
 */
export function orderPublications(publications: readonly Publication[]): Publication[] {
  const position = new Map(publications.map((row, index) => [row.id, index]));
  const stamp = (row: Publication) => {
    const value = row.publishedAt || row.discoveredAt || "";
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
  };
  return [...publications].sort(
    (a, b) =>
      stamp(b) - stamp(a) ||
      (position.get(a.id) ?? 0) - (position.get(b.id) ?? 0),
  );
}

/** §19: the working set, or the whole list once the editor asks for it. */
export function visiblePublications(
  publications: readonly Publication[],
  expanded: boolean,
): Publication[] {
  const ordered = orderPublications(publications);
  return expanded ? ordered : ordered.slice(0, PUBLICATIONS_PREVIEW);
}

/** §19: whether the "show all" control has anything to show. */
export function hasHiddenPublications(
  publications: readonly Publication[],
  expanded: boolean,
): boolean {
  return !expanded && publications.length > PUBLICATIONS_PREVIEW;
}

/**
 * §22: an Article's state word, when the projection carries one. `null` means
 * the Article is finalized and lives in the Archive, or that the projection is
 * older than the field — never "preparation" guessed in its place.
 */
export function articleStateLabel(state: ArticleState | null | undefined): string | null {
  if (state === "preparation") return "Подготовка";
  if (state === "draft") return "Чернова";
  if (state === "ready") return "Готова";
  return null;
}

/**
 * §15/§29: whether research is this Story's next editorial step.
 *
 * Research is the forward move exactly when the backend offers it for a Story
 * that is unassessed or has a real gap. That is the whole decision: the backend
 * already refuses to offer research for an assessed clean basis, so the page
 * never has to re-derive it.
 */
export function isResearchForward(story: StoryDetail): boolean {
  return (
    story.availableActions.includes("RESEARCH_MORE") &&
    (isUnassessed(story) || realGaps(story).length > 0)
  );
}

/**
 * §23/§29: the one filled forward action in the **header**.
 *
 * `Започни статия` is the strong move only when nothing else is more urgent:
 * the Story has no Article yet, and no research round to run first. In every
 * other case it is still rendered — the backend offered it, and §5 makes the
 * backend the authority — but outlined, because the Article block (a Story that
 * already has one) or the research control is where the decision really is.
 *
 * Research is deliberately *not* a header action. §15 wants the research control
 * inside or directly below `Какво липсва`, and §2's own hierarchy puts
 * "Research / next step" after "What is missing". Rendering the same command
 * twice on one page would be the "row of five equal buttons" §29 warns against,
 * so the single research control lives in the gaps block and carries the filled
 * treatment there. The header simply shows no strong action in that state.
 *
 * The return value is a *choice among offered actions*, never a new one.
 */
export type StoryHeaderPrimaryAction = "START_ARTICLE" | null;

export function headerPrimaryAction(story: StoryDetail): StoryHeaderPrimaryAction {
  if (isResearchForward(story)) return null;
  if (story.availableActions.includes("START_ARTICLE") && story.relatedArticles.length === 0) {
    return "START_ARTICLE";
  }
  return null;
}
