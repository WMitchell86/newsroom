import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createIdempotencyKey,
  REWRITE_LENGTHS,
  REWRITE_MODES,
  rewriteArticle,
  updateArticleVoice,
} from "../api/client";
import { invalidateArticleProjections, queryKeys } from "../api/queries";
import { getErrorMessage } from "../shared/errorMessage";
import type { ArticleProjection } from "../api/dto";
import type { ArticleAutosave } from "./useArticleAutosave";
import { saveLabel } from "./articleSaveLabel";
import styles from "./ArticleWorkspace.module.css";

/**
 * V1.2-G3 §7/§8: the Article title, in the header, directly editable.
 *
 * The `<h1>` is the page's own heading; the input inside it carries the
 * accessible name, so a screen reader announces the title field as a title
 * field inside the page heading. It is BORDERLESS and grows into the page
 * title on focus, so an editable headline does not look like a form.
 *
 * It is fed by the SAME `useArticleAutosave` as the body. There is exactly one
 * writer per Article: a separate title save would be a second optimistic-
 * concurrency writer racing the body for the same content version, which is
 * the C3 defect class this page must not reintroduce.
 */
export function ArticleDeskTitle({
  autosave,
  editable,
}: {
  autosave: ArticleAutosave;
  /** The title is editable only while the editor is actually editing. */
  editable: boolean;
}) {
  const [focused, setFocused] = useState(false);
  const status = saveLabel(autosave.status);

  if (!editable) {
    // §26: a Ready Article is calm and nearly finished. Nothing on the page is
    // an editable field until the editor explicitly reopens it for editing, so
    // there is no accidental write and no stray focus ring on a finished text.
    return <div className={styles.titleBlock}>
      <h1 className={styles.deskTitleStatic}>{autosave.title}</h1>
    </div>;
  }

  return <div className={styles.titleBlock}>
    <h1 className={styles.deskTitle}>
      <input
        className={focused
          ? `${styles.deskTitleInput} ${styles.deskTitleInputFocused}`
          : styles.deskTitleInput}
        id="article-working-title"
        value={autosave.title}
        aria-label="Заглавие"
        onChange={(event) => autosave.change({ title: event.target.value })}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          void autosave.flush();
        }}
      />
    </h1>
    {status ? <p className={styles.saveStatus} role="status" aria-live="polite">{status}</p> : null}
    {autosave.navigationWarning ? (
      <p className={styles.navigationWarning} role="alert">{autosave.navigationWarning}</p>
    ) : null}
  </div>;
}

/**
 * V1.2-G3 §12: the Focus on a Draft or Ready Article.
 *
 * It matters, but it must not compete with the text. The block is collapsed to
 * the Focus sentence and a `Промени` control; it is never a large textarea
 * above every Draft. The backend decides whether the Focus can be changed at
 * all — the control is rendered only when `CHANGE_FOCUS`/`SELECT_FOCUS` is
 * actually offered.
 */
export function DraftFocusBlock({ article }: { article: ArticleProjection }) {
  const [open, setOpen] = useState(false);
  const canChange = article.availableActions.includes("CHANGE_FOCUS")
    || article.availableActions.includes("SELECT_FOCUS");
  const focus = article.editorialFocus.text;

  return <section className={styles.draftFocus} aria-labelledby="article-draft-focus">
    <div className={styles.draftFocusBar}>
      <h2 className={styles.contextLabel} id="article-draft-focus">Фокус</h2>
      {canChange ? <button
        className={styles.quietAction}
        type="button"
        aria-expanded={open}
        aria-controls="article-draft-focus-body"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Скрий" : "Промени"}
      </button> : null}
    </div>
    {open ? <div id="article-draft-focus-body">
      {focus
        ? <p className={styles.focusText}>{focus}</p>
        : <p className={styles.focusEmpty}>Още не е зададен фокус.</p>}
    </div> : <p className={styles.focusSummary}>
      {focus || "Още не е зададен фокус."}
    </p>}
  </section>;
}

/**
 * V1.2-G4.3 §D — the optional Voice control, as progressive disclosure.
 *
 * It sits directly under the Focus because that is where an editor thinks about
 * "what angle is this" and "whose voice is it" - and it is deliberately ONE
 * line that expands on demand. A permanent Voice dropdown next to every Draft
 * would be a configuration surface the editor has to read past on every article.
 *
 * The three rules it must never break:
 *   - changing it does NOT create an Article;
 *   - changing it does NOT rewrite the text on screen;
 *   - it applies to the NEXT Draft or Rewrite.
 * The wording below says so, because a control whose effect is invisible is
 * indistinguishable from a broken one.
 */
export function ArticleStyleBlock({ article }: { article: ArticleProjection }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const style = article.style;

  const choose = useMutation({
    mutationFn: (voice: string) => updateArticleVoice(article.id, voice),
    onSuccess: async (projection) => {
      queryClient.setQueryData(queryKeys.article(projection.id), projection);
      await invalidateArticleProjections(queryClient, projection.id, projection.story.id);
      setOpen(false);
    },
  });

  return <section className={styles.draftFocus} aria-labelledby="article-style">
    <div className={styles.draftFocusBar}>
      <h2 className={styles.contextLabel} id="article-style">Стил</h2>
      <button
        className={styles.quietAction}
        type="button"
        aria-expanded={open}
        aria-controls="article-style-body"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Скрий" : "Промени"}
      </button>
    </div>
    {open ? <div id="article-style-body">
      <p className={styles.focusSummary}>{style.label}</p>
      <ul className={styles.preparationList}>
        {style.options.map((option) => <li key={option.id}>
          <button
            className={styles.quietAction}
            type="button"
            aria-pressed={option.id === style.voice}
            disabled={choose.isPending}
            onClick={() => choose.mutate(option.id)}
          >
            {option.label}
          </button>
        </li>)}
      </ul>
      {choose.isError ? <p className={styles.readyError} role="alert">
        {getErrorMessage(choose.error, "Стилът не можа да бъде запазен. Опитайте отново.")}
      </p> : null}
      <p className={styles.focusSummary}>
        Промяната се отнася за следващата чернова или пренаписване. Текстът на статията не се променя.
      </p>
    </div> : <p className={styles.focusSummary}>{style.label}</p>}
  </section>;
}

/**
 * V1.2-G4.3 §E — `Пренапиши`, the editor's normal way back into the writing.
 *
 * The editor reads the draft, says what is wrong in ordinary language, and gets
 * a new version of the SAME article. There is no wizard, no research step and
 * no second Article: the comment is the whole instruction.
 *
 * §E4 - the comment stays in local state until the operation succeeds, so a
 * failed rewrite never costs the editor the words they just typed, and a
 * successful one clears the box because the intent has been carried out.
 */
export function RewriteBlock({ article }: { article: ArticleProjection }) {
  const [comment, setComment] = useState("");
  // V1.2-G4.18. Two controls the editor did not have before. Both exist
  // because of a measured failure: this Article's material is auto-suggested
  // MODE_BRIEF, whose prompt tells the model "1-2 dense paragraphs, do not
  // inflate to a feature" — so typing "разшири до пълна статия" produced a
  // draft 85 characters SHORTER than the one it replaced. The mode and the
  // length are the two ways the editor's own instruction gets to win.
  const [mode, setMode] = useState("");
  const [length, setLength] = useState("");
  const [key, setKey] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const rewrite = useMutation({
    mutationFn: () =>
      rewriteArticle(article.id, comment, key ?? createIdempotencyKey(), { mode, length }),
    onMutate: () => {
      // One key per attempt, reused by any retry of that same attempt, so a
      // double click or a lost response cannot produce two rewrites.
      setKey(createIdempotencyKey());
    },
    onSuccess: async (projection) => {
      queryClient.setQueryData(queryKeys.article(projection.id), projection);
      await invalidateArticleProjections(queryClient, projection.id, projection.story.id);
      setComment("");
      setKey(null);
    },
    onError: () => {
      // The comment is deliberately NOT cleared: §E4 keeps the editor's words.
      setKey(null);
    },
  });

  return <section className={styles.rewriteBlock} aria-labelledby="article-rewrite">
    <h2 className={styles.contextLabel} id="article-rewrite">Какво да променя?</h2>
    <label className={styles.contextLabel} htmlFor="article-rewrite-comment">
      Коментар за пренаписването
    </label>
    <textarea
      className={styles.rewriteInput}
      id="article-rewrite-comment"
      value={comment}
      rows={3}
      placeholder="Например: направи текста по-кратък и започни директно с основния факт."
      onChange={(event) => setComment(event.target.value)}
    />
    {/*
      V1.2-G4.18. The controls sit BESIDE the comment, not hidden in it: the
      failure being fixed was an instruction and a mode fighting silently, so
      the editor has to be able to see which one is in force.
    */}
    <div className={styles.rewriteControls}>
      <label className={styles.contextLabel} htmlFor="article-rewrite-length">
        Дължина
      </label>
      <select
        id="article-rewrite-length"
        className={styles.rewriteSelect}
        value={length}
        onChange={(event) => setLength(event.target.value)}
      >
        {REWRITE_LENGTHS.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>

      <label className={styles.contextLabel} htmlFor="article-rewrite-mode">
        Формат
      </label>
      <select
        id="article-rewrite-mode"
        className={styles.rewriteSelect}
        value={mode}
        onChange={(event) => setMode(event.target.value)}
      >
        {REWRITE_MODES.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </div>
    <div className={styles.rewriteActions}>
      <button
        className={styles.quietAction}
        type="button"
        disabled={!comment.trim() || rewrite.isPending}
        onClick={() => rewrite.mutate()}
      >
        {rewrite.isPending ? "Пренаписва се…" : "Пренапиши"}
      </button>
      {rewrite.isPending ? <p className={styles.readyFeedback} role="status" aria-live="polite">
        Работи се по текста.
      </p> : null}
    </div>
    {rewrite.isError ? <p className={styles.readyError} role="alert">
      {getErrorMessage(rewrite.error, "Пренаписването не можа да се извърши. Опитайте отново.")}
    </p> : null}
  </section>;
}
