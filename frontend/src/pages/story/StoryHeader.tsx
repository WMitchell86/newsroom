import { Link } from "react-router-dom";
import type { RefObject } from "react";
import type { StoryDetail } from "../../api/dto";
import { formatRelativeTime, publisherCountLabel } from "../../shared/editorLabels";
import styles from "./Story.module.css";

export interface StoryHeaderProps {
  story: StoryDetail;
  /** One instant for the whole render, so two labels cannot disagree. */
  now: Date;
  headingRef: RefObject<HTMLHeadingElement | null>;
}

/**
 * V1.2-G2 §3/§4/§30: the top of the Story.
 *
 * Three things only: a quiet way back, the headline in full, and the compact
 * metadata the backend actually holds — the last change, the independent
 * publisher count, and the reviewed/followed/ignored state. Locality, category,
 * importance and score are deliberately absent: `category` is not part of the
 * canonical Story schema, and nothing here may be inferred from the headline.
 *
 * A publisher count of zero is not printed either. A Story whose members carry
 * no publisher identity has an *unknown* count, not a measured zero.
 */
export function StoryHeader({ story, now, headingRef }: StoryHeaderProps) {
  const publishers = publisherCountLabel(story.publisherCount);
  const changed = story.latestChangeAt ? formatRelativeTime(story.latestChangeAt, now) : null;

  return (
    <header className={styles.header ?? ""}>
      <Link className={styles.back} to="/stories">
        ← Истории
      </Link>
      <p className={styles.kicker}>История</p>
      <h1 ref={headingRef} tabIndex={-1} className={styles.title}>
        {story.title}
      </h1>
      <p className={styles.meta}>
        {changed ? <span>Последна промяна: {changed}</span> : null}
        {publishers ? <span>{publishers}</span> : null}
        <span>Прегледана: {story.reviewed ? "да" : "не"}</span>
        <span>Следена: {story.followed ? "да" : "не"}</span>
        {story.ignored ? <span>Игнорирана</span> : null}
      </p>
      {/* §26: the ignored state is explained where it is declared, not in a
          separate warning zone at the top of the page. */}
      {story.ignored ? (
        <p className={styles.ignoredNotice} role="note">
          Тази история е извън фокуса на „Днес“. Прегледът ѝ връща към обичайното редакционно
          състояние.
        </p>
      ) : null}
    </header>
  );
}
