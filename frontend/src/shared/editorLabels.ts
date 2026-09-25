import type { ArticleState, NextAction } from "../api/dto";

export const articleStateLabels: Record<ArticleState, string> = {
  preparation: "Подготовка",
  draft: "Чернова",
  ready: "Готова",
};

const dateFormatter = new Intl.DateTimeFormat("bg-BG", {
  day: "numeric",
  month: "long",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const shortDateFormatter = new Intl.DateTimeFormat("bg-BG", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

export function formatDate(value: string | null | undefined, withTime = true): string {
  if (!value) return "Няма дата";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Няма дата";
  return (withTime ? dateFormatter : shortDateFormatter).format(date);
}

export function actionLabel(action: NextAction | null): string {
  return action?.label ?? "Отвори";
}

export function isStoryAttention(value: string): boolean {
  return value === "new" || value === "developments";
}
