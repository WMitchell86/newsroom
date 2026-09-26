import type { StoryDetail } from "../../api/dto";
import { formatRelativeTime, isRedundantSummary } from "../../shared/editorLabels";
import { Section } from "../../shared/EditorPrimitives";
import styles from "./Story.module.css";

export interface StoryContextProps {
  story: StoryDetail;
  now: Date;
}

/**
 * V1.2-G2 §2/§21: "Какво се случи" — the Story's own account of itself, with
 * the developments the backend classified as meaningful directly beneath it.
 *
 * A development is a property of the canonical Story, not something React
 * decides: the list comes from `newDevelopments`, and a publication that merely
 * belongs to the Story is not promoted into one. The label is the same restrained
 * word, never a new Story status and never a badge that implies importance.
 */
export function StoryContext({ story, now }: StoryContextProps) {
  const summary = story.whatHappened || story.summary;
  // §4: never print the headline twice. A context line that is the title with
  // different punctuation is not information.
  const prose = summary && !isRedundantSummary(story.title, summary) ? summary : null;
  const developments = story.newDevelopments.filter((item) => item.unreviewed);

  if (!prose && developments.length === 0) return null;

  return (
    <Section title="Какво се случи">
      {prose ? <p className={styles.prose}>{prose}</p> : null}
      {developments.length ? (
        <ul className={styles.developmentList}>
          {developments.map((development) => (
            <li className={styles.gap} key={development.id}>
              <span className={styles.gapKind}>Ново развитие</span>
              <h3 className={styles.developmentTitle}>{development.title}</h3>
              <p className={styles.sourceLine}>
                {formatRelativeTime(development.changedAt, now)}
                {development.summary ? ` · ${development.summary}` : null}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}
