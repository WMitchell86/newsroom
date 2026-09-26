import type { MissingInformationItem, StoryDetail } from "../../api/dto";
import { Section } from "../../shared/EditorPrimitives";
import { isResearchForward, isUnassessed, realGaps } from "./storyView";
import styles from "./Story.module.css";

export interface StoryResearchControl {
  available: boolean;
  pending: boolean;
  /** The backend's own sentence for a failed round, or `null`. */
  error: string | null;
  onResearch(): void;
}

export interface StoryGapListProps {
  story: StoryDetail;
  research: StoryResearchControl;
}

const gapKindLabels: Record<MissingInformationItem["kind"], string> = {
  missing_fact: "Липсва факт",
  conflict: "Противоречие",
  unresolved: "Неизяснен въпрос",
};

/**
 * V1.2-G2 §9/§14/§15/§16/§17: "Какво липсва", and the research that answers it.
 *
 * The section is rendered only when there is something real to say. An assessed
 * Story with no gaps gets no section and no "Няма" line: a silent clean basis is
 * not a thing the editor needs to be told about, and an invented reassurance is
 * worse than silence.
 *
 * An unassessed Story gets exactly one honest sentence and the action that
 * changes it — never three empty panels saying so.
 *
 * A blocking gap is a real editorial obstacle and is marked with a warm rule
 * and the plain word "пречи"; a non-blocking one is context and stays neutral.
 * The internal classification (`BLOCKING_GAP` and friends) is never rendered.
 *
 * While a round runs the control says one calm thing — `Проучва се…` — and while
 * it fails, the backend's own sentence appears beside the gaps. The already
 * confirmed facts and the existing gaps are untouched by a failure: a failed
 * round adds nothing and removes nothing.
 */
export function StoryGapList({ story, research }: StoryGapListProps) {
  const gaps = realGaps(story);
  const unassessed = isUnassessed(story);
  if (!gaps.length && !unassessed) return null;

  // §29: the single strong action of the page lives here, in the block that
  // says what is missing, so "missing information → research" is one gesture.
  // It is the filled control exactly when research is the next step.
  const researchButton = (
    <div className={styles.researchControl}>
      <button
        className={isResearchForward(story) ? styles.primary : styles.quiet}
        type="button"
        disabled={research.pending}
        onClick={research.onResearch}
        data-research-trigger="missing-information"
      >
        {research.pending ? "Проучва се…" : "Проучи още"}
      </button>
      {research.pending ? (
        <span className={styles.researchStatus} role="status" aria-live="polite">
          Проучването е в ход.
        </span>
      ) : null}
    </div>
  );

  if (!gaps.length) {
    return (
      <div className={styles.unassessed}>
        <p className={styles.unassessedText}>Историята още не е проучена.</p>
        {research.available ? researchButton : null}
        {research.error ? (
          <p className={styles.researchError} role="alert">
            {research.error}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <Section title="Какво липсва" meta={String(gaps.length)}>
      <ul className={styles.gapList}>
        {gaps.map((gap) => (
          <li
            className={`${styles.gap} ${gap.blocking ? styles.gapBlocking : ""}`}
            key={gap.id}
          >
            <span className={styles.gapKind}>
              {gapKindLabels[gap.kind]}
              {/* §14: the plain word, not the internal enum. */}
              {gap.blocking ? <span className={styles.gapBlockingTag}>· пречи</span> : null}
            </span>
            <p className={styles.gapQuestion}>{gap.question}</p>
            {gap.reason ? <p className={styles.gapReason}>{gap.reason}</p> : null}
          </li>
        ))}
      </ul>
      {research.available ? researchButton : null}
      {research.error ? (
        <p className={styles.researchError} role="alert">
          {research.error}
        </p>
      ) : null}
    </Section>
  );
}
