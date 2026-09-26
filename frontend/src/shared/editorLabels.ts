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

export function actionLabel(action: NextAction | null): string {
  return action?.label ?? "Отвори";
}

export function isStoryAttention(value: string): boolean {
  return value === "new" || value === "developments";
}
