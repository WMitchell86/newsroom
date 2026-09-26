import type { ArticleState, LastRefresh, NextAction } from "../api/dto";

export const articleStateLabels: Record<ArticleState, string> = {
  preparation: "Подготовка",
  draft: "Чернова",
  ready: "Готова",
};

/**
 * The newsroom's editorial timezone, pinned explicitly.
 *
 * The browser's own timezone is never used: a run finished at 04:32 UTC is
 * 07:32 in the newsroom, and the editor must read the newsroom's clock. An
 * explicit zone also keeps the rendered value stable when the same DTO is
 * screenshotted on a machine set to UTC.
 */
const NEWSROOM_TIME_ZONE = "Europe/Sofia";

const dateFormatter = new Intl.DateTimeFormat("bg-BG", {
  day: "numeric",
  month: "long",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: NEWSROOM_TIME_ZONE,
});

const shortDateFormatter = new Intl.DateTimeFormat("bg-BG", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: NEWSROOM_TIME_ZONE,
});

const timeFormatter = new Intl.DateTimeFormat("bg-BG", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: NEWSROOM_TIME_ZONE,
});

export function formatDate(value: string | null | undefined, withTime = true): string {
  if (!value) return "Няма дата";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Няма дата";
  return (withTime ? dateFormatter : shortDateFormatter).format(date);
}

function sofiaDayKey(value: string | Date): string | null {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return null;
  // `en-CA` formats as YYYY-MM-DD, which is a comparable calendar key.
  return new Intl.DateTimeFormat("en-CA", { timeZone: NEWSROOM_TIME_ZONE }).format(date);
}

/**
 * D1: when the newsroom was last refreshed, in words the editor can act on.
 *
 * A run from earlier today is just a time. Yesterday is named, because
 * "вчера" is the case an editor most often needs to recognise. Anything older
 * states its date, so a stale run can never be mistaken for a fresh one.
 * Returns `null` for a never-run install, which the page renders as an
 * explicit first-run state instead of a placeholder dash.
 */
export function formatLastRefresh(
  refresh: LastRefresh | null,
  now: Date = new Date(),
): string | null {
  if (!refresh) return null;
  const finished = new Date(refresh.finishedAt);
  if (Number.isNaN(finished.getTime())) return null;
  const finishedDay = sofiaDayKey(finished);
  const today = sofiaDayKey(now);
  if (!finishedDay || !today) return null;
  const time = timeFormatter.format(finished);
  if (finishedDay === today) return time;
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (finishedDay === sofiaDayKey(yesterday)) return `вчера, ${time}`;
  return `${shortDateFormatter.format(finished)}, ${time}`;
}

/** `37 нови публикации` / `1 нова публикация` — the count the run really produced. */
export function newPublicationsLabel(count: number): string {
  if (count === 1) return "1 нова публикация";
  return `${count} нови публикации`;
}

/**
 * V1.2-G1 §12/§14: how recently a row changed, in the words a newsroom uses.
 *
 * A wire row is scanned by recency, so "преди 18 мин" carries the decision and
 * the exact clock time is available beside it. Anything older than a couple of
 * days falls back to the calendar date, because "преди 12 дни" stops being
 * useful for judging whether a Story is still live.
 */
export function formatRelativeTime(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return "няма дата";
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return "няма дата";
  const minutes = Math.max(0, Math.round((now.getTime() - moment.getTime()) / 60_000));
  if (minutes < 1) return "току-що";
  if (minutes < 60) return `преди ${minutes} мин`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `преди ${hours} ч`;
  const days = Math.round(hours / 24);
  if (days <= 2) return `преди ${days} дни`;
  return formatDate(value, false);
}

/**
 * V1.2-G1 §15: independent-publisher count, in Bulgarian plural.
 *
 * `0` is not rendered as "0 източници": a Story whose members carry no
 * publisher identity has an *unknown* count, not a measured zero, and printing
 * the zero would state a fact the store cannot support.
 */
export function publisherCountLabel(count: number | null | undefined): string | null {
  if (typeof count !== "number" || !Number.isFinite(count) || count <= 0) return null;
  if (count === 1) return "1 източник";
  return `${count} източника`;
}

/**
 * V1.2-G1 §14: whether a "summary" is really the headline again.
 *
 * Feeds routinely carry a summary that is the title with trailing punctuation
 * or a source suffix. Rendering that under the headline makes a row look
 * padded and trains the editor to skip the line that should carry new
 * information. Comparison is on a normalized form: case, punctuation and
 * whitespace are dropped, and a summary that is a prefix of the title counts
 * as the same text.
 */
export function isRedundantSummary(title: string, summary: string): boolean {
  const normalize = (value: string) =>
    value
      .toLocaleLowerCase("bg-BG")
      .replace(/[«»"'“”‘’.,:;!?–—-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  const normalizedTitle = normalize(title);
  const normalizedSummary = normalize(summary);
  if (!normalizedSummary) return true;
  if (normalizedSummary === normalizedTitle) return true;
  return (
    normalizedTitle.startsWith(normalizedSummary) || normalizedSummary.startsWith(normalizedTitle)
  );
}

export function actionLabel(action: NextAction | null): string {
  return action?.label ?? "Отвори";
}

export function isStoryAttention(value: string): boolean {
  return value === "new" || value === "developments";
}
