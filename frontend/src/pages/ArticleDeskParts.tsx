import { useState } from "react";
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
