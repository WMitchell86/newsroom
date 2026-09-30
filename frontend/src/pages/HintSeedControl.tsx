import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { seedStoriesFromHint, type HintSeedResult } from "../api/client";
import styles from "./ArticleWorkspace.module.css";

/**
 * «Започни от идея» (V1.2-G4.20).
 *
 * The editor names a topic; the server searches, OPENS what it finds and
 * returns real pages as ordinary Stories. The hint is never evidence, so this
 * control never opens a draft, never claims a source, and never pretends the
 * editor's words became an article.
 *
 * The report is deliberately literal. "0 found" says zero, and a page that
 * could not be opened is named with its own failure category — a timeout is
 * shown as a timeout, never folded into "no material exists". An editor who
 * cannot tell those apart cannot decide what to do next, and the alternative
 * — a confident sentence the system did not observe — is the failure this
 * whole feature was built to avoid.
 *
 * On success the editor is taken to the FIRST new story, because the point of
 * naming a topic was to go and write about it.
 */
export function HintSeedControl({ onSeeded }: { onSeeded?: () => void }) {
  const [open, setOpen] = useState(false);
  const [hint, setHint] = useState("");
  const [result, setResult] = useState<HintSeedResult | null>(null);
  const [error, setError] = useState("");

  const seed = useMutation({
    mutationFn: () => seedStoriesFromHint(hint.trim()),
    onMutate: () => {
      setError("");
      setResult(null);
    },
    onSuccess: (data) => {
      setResult(data);
      onSeeded?.();
      // Deliberately NOT navigating away. An earlier version jumped to the new
      // story the moment the request returned, which unmounted this component
      // and made the report below unreadable — the editor was told "3 pages
      // opened" by code that then removed the sentence before it could be
      // read. The report is the part that carries the promise, so it stays,
      // and the story is one click away inside it.
    },
    onError: (exc: Error) => {
      setError(exc.message || "Подсказката не можа да бъде използвана.");
    },
  });

  if (!open) {
    return (
      <button
        className="styles.secondaryAction"
        type="button"
        onClick={() => setOpen(true)}
        data-testid="hint-seed-open"
      >
        Започни от идея
      </button>
    );
  }

  return (
    <div className="styles.preparationSection" data-testid="hint-seed-panel">
      <label className="styles.editorLabel" htmlFor="hint-seed-input">
        Темата, за която искаш да пишем
      </label>
      <input
        id="hint-seed-input"
        className="styles.rewriteInput"
        value={hint}
        maxLength={300}
        placeholder="напр. проверка на машините за изборите"
        onChange={(event) => setHint(event.target.value)}
      />
      <div className="styles.rewriteControls">
        <button
          className="styles.primaryAction"
          type="button"
          disabled={seed.isPending || hint.trim().length < 6}
          onClick={() => seed.mutate()}
          data-testid="hint-seed-run"
        >
          {seed.isPending ? "Търси се…" : "Потърси и отвори"}
        </button>
        <button
          className="styles.secondaryAction"
          type="button"
          onClick={() => {
            setOpen(false);
            setHint("");
            setResult(null);
            setError("");
          }}
          data-testid="hint-seed-cancel"
        >
          Отказ
        </button>
      </div>
      {error ? (
        <p className="styles.fieldError" role="alert" data-testid="hint-seed-error">
          {error}
        </p>
      ) : null}
      {result ? (
        <div className="styles.searchNote" data-testid="hint-seed-report">
          {result.openedCount > 0 ? (
            <>
              <p>
                Отворени са {result.openedCount} страници. Всяка е записана като Story
                {result.opened.length > 1 ? " и може да се проучи отделно" : ""}.
              </p>
              {/* Only a real story id is a route. `/stories/:id` answers
                  «Невалиден Story.» for a raw inbox item id, so the link is
                  rendered from the story id or not at all. */}
              <ul className={styles.missingList}>
                {result.opened.map((page) => (
                  <li key={page.storyId || page.url}>
                    {page.storyId ? (
                      <a
                        className={styles.sourceLink}
                        href={`/stories/${encodeURIComponent(page.storyId)}`}
                      >
                        {page.title || page.url}
                      </a>
                    ) : (
                      page.title || page.url
                    )}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {/* Three outcomes, never collapsed into one sentence. `openedCount` is
              how many were WRITTEN, and when it is 0 the pages may still have
              opened and been dropped on purpose. Saying "not a single page was
              opened" about a page that opened, and that we excluded because it
              is our own article, is a false statement about our own work — and
              the list directly beneath it would contradict it. */}
          {result.openedCount === 0 && (result.skipped ?? []).length > 0 ? (
            <p data-testid="hint-seed-excluded">
              Отворени са {result.skipped.length} страници, но нито една не е
              записана като материал.
            </p>
          ) : null}
          {result.openedCount === 0 && (result.skipped ?? []).length === 0 ? (
            // Said plainly, and not dressed up as a broken system.
            <p>
              Не се отвори нито една страница по тази подсказка
              {result.considered > 0
                ? ` — ${result.considered} бяха намерени, но не се отвориха.`
                : " — търсенето не върна резултати."}
            </p>
          ) : null}
          {/* Defensive on purpose: these fields were added after the report was
              written, and the unguarded `.length` beside them had the same
              shape. A response that predates one must not blank the whole
              report with a TypeError. */}
          {(result.skipped ?? []).length > 0 ? (
            <ul className={styles.missingList} data-testid="hint-seed-skipped">
              {result.skipped.map((page) => (
                <li key={page.url}>
                  {page.title || page.url} —{" "}
                  {page.reason === "circular"
                    ? "собствена публикувана статия, не е материал"
                    : "издателът е забранен за редакцията"}
                </li>
              ))}
            </ul>
          ) : null}
          {(result.unopened ?? []).length > 0 ? (
            <ul className="styles.missingList" data-testid="hint-seed-failures">
              {result.unopened.map((item) => (
                <li key={item.url}>
                  {item.url} — {item.status}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
