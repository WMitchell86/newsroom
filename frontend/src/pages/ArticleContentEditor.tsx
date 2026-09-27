import type { ArticleAutosave } from "./useArticleAutosave";
import styles from "./ArticleWorkspace.module.css";

/**
 * V1.2-G3 §13: THE article-body control.
 *
 * There is exactly one. The C3 defect was a second textarea bound to the same
 * state under the same DOM id, which made the labelled control a duplicate and
 * every test drive the orphan. That fix is preserved structurally: this
 * component owns NO state of its own, so it cannot grow a second control, and
 * the title moved to the header on the SAME autosave.
 *
 * §5: the writing surface. A comfortable measure, generous vertical space and
 * typography chosen for a 500-1000 word Bulgarian article rather than for a
 * form. The chrome around it is thin on purpose - this is a writing desk.
 *
 * §14: persistence is unchanged. The debounce, the blur flush, the serialized
 * writes, the optimistic concurrency, the navigation flush and the conflict
 * handling all live in `useArticleAutosave`; this component only draws.
 */
export function ArticleContentEditor({ autosave }: { autosave: ArticleAutosave }) {
  return <div className={styles.editorShell}>
    <label className={styles.editorLabel} htmlFor="article-working-body">Текст на статията</label>
    <textarea
      className={styles.editorBody}
      id="article-working-body"
      value={autosave.body}
      onChange={(event) => autosave.change({ body: event.target.value })}
      onBlur={() => void autosave.flush()}
    />
    {autosave.status === "error" && !autosave.serverConflict ? (
      <button className={styles.quietAction} type="button" onClick={() => void autosave.flush()}>
        Опитайте отново
      </button>
    ) : null}
    {autosave.serverConflict ? <section className={styles.conflict} role="alert" aria-labelledby="article-conflict-title">
      <h3 id="article-conflict-title">Черновата е променена в друга сесия.</h3>
      <p>Локалните промени са запазени.</p>
      <div className={styles.conflictActions}>
        <button type="button" onClick={autosave.useLocalChanges}>Използвай моите промени</button>
        <button type="button" onClick={autosave.loadServerVersion}>Зареди запазената версия</button>
      </div>
    </section> : null}
  </div>;
}
