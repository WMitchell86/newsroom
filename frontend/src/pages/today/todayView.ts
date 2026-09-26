/**
 * V1.2-G1: the pure view logic behind the Today screen.
 *
 * Search, grouping and sorting live here, away from the markup, because these
 * are the three places where this slice could most easily start inventing
 * product state. The rules they follow:
 *
 *   * **Search** covers only what the Today DTO actually carries. There is no
 *     archive index, no publisher list and no full-text engine behind it, and
 *     the UI never claims otherwise.
 *   * **Tabs** are a partition of the two groups the backend already returns.
 *     No third status is invented to fill a fourth slot.
 *   * **Sorting** is a view preference over rows the server already sent. It
 *     never re-orders the underlying projection, and it never writes.
 */

import type { TodayAttention, TodayProjection } from "../../api/dto";

/** A Story attention row: the only kind that carries a publisher count. */
export type TodayStoryRow = Extract<TodayAttention, { objectType: "story" }>;

/**
 * §8: the compact attention groups.
 *
 * Each one maps to a real backend group. There is deliberately no
 * "Изискват внимание" tab: Today has no such field, and inventing a workflow
 * status to fill the mockup would be a lie the editor could act on wrongly.
 */
export type TodayTab = "all" | "new" | "developments";

/** §9: the sort options this slice can support truthfully. */
export type TodaySort = "newest" | "publishers";

export const todayTabs: ReadonlyArray<{ value: TodayTab; label: string }> = [
  { value: "all", label: "Всички" },
  { value: "new", label: "Нови" },
  { value: "developments", label: "В развитие" },
];

export const todaySorts: ReadonlyArray<{ value: TodaySort; label: string }> = [
  { value: "newest", label: "Най-нови" },
  { value: "publishers", label: "Най-много източници" },
];

/** Every Story row Today holds, newest-last as the two groups arrive. */
export function storyRows(projection: TodayProjection): TodayStoryRow[] {
  const all: TodayAttention[] = [...projection.newDevelopments, ...projection.newStories];
  return all.filter(
    (row): row is TodayStoryRow => row.objectType === "story",
  );
}

/** The count each tab truthfully shows, including the ones it would hide. */
export function tabCounts(projection: TodayProjection): Record<TodayTab, number> {
  const newStories = projection.newStories.filter((row) => row.objectType === "story").length;
  const developments = projection.newDevelopments.filter(
    (row) => row.objectType === "story",
  ).length;
  return { all: newStories + developments, new: newStories, developments };
}

/** §8: the rows one tab owns. `all` is every Story row, unfiltered. */
export function selectTab(projection: TodayProjection, tab: TodayTab): TodayStoryRow[] {
  const rows = storyRows(projection);
  if (tab === "new") return rows.filter((row) => row.reason === "NEW_STORY");
  if (tab === "developments") {
    return rows.filter((row) => row.reason === "UNREVIEWED_DEVELOPMENT");
  }
  return rows;
}

/**
 * §10/§11: ordering, as a view preference.
 *
 * `newest` is the canonical `latestChangeAt` the editor already reads, newest
 * first, and it reproduces the order the backend delivers. `publishers` is
 * descending independent-publisher count with the same timestamp as the stable
 * tie-breaker, so equal counts never appear in a random order.
 *
 * The input array is never mutated: a sorted view must not be able to disturb
 * the projection another consumer is reading.
 */
export function sortStoryRows(rows: TodayStoryRow[], sort: TodaySort): TodayStoryRow[] {
  // Position is captured before sorting, so rows the comparator considers equal
  // keep the order the server delivered them in.
  const position = new Map(rows.map((row, index) => [row.objectId, index]));
  const stable = (a: TodayStoryRow, b: TodayStoryRow) =>
    (position.get(a.objectId) ?? 0) - (position.get(b.objectId) ?? 0);
  if (sort === "newest") {
    return [...rows].sort(
      (a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp) || stable(a, b),
    );
  }
  return [...rows].sort(
    (a, b) => (b.publisherCount ?? 0) - (a.publisherCount ?? 0) || stable(a, b),
  );
}

/**
 * §6: client-side search over the loaded, bounded Today set.
 *
 * The only fields searched are the ones the row actually shows: the headline and
 * the summary. Publisher *names* are not in the Today projection, so they are
 * not searched — adding them would mean widening the projection beyond the one
 * field this slice is allowed to add.
 */
export function matchesQuery(row: TodayStoryRow, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase("bg-BG");
  if (!needle) return true;
  return (
    row.title.toLocaleLowerCase("bg-BG").includes(needle) ||
    row.summary.toLocaleLowerCase("bg-BG").includes(needle)
  );
}

/** Search applied to a tab's rows, before sorting. */
export function filterRows(rows: TodayStoryRow[], query: string): TodayStoryRow[] {
  return rows.filter((row) => matchesQuery(row, query));
}