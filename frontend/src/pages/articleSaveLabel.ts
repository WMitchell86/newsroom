import type { ArticleAutosave } from "./useArticleAutosave";

/**
 * V1.2-G3 §8: the passive save state, beside the title.
 *
 * Three words, no more. There is deliberately no Save button, no version
 * number, no concurrency id and no API error here: autosave is the whole
 * contract, and the editor only needs to know whether it landed.
 */
export function saveLabel(status: ArticleAutosave["status"]): string | null {
  if (status === "saving") return "Запазва се…";
  if (status === "saved") return "Запазено";
  if (status === "error") return "Неуспешно запазване";
  if (status === "conflict") return "Промени в друга сесия";
  return null;
}
