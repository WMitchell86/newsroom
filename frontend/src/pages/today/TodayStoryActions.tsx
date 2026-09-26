import { Link } from "react-router-dom";
import styles from "./Today.module.css";

/** §16: the one visually strong forward action on a Today row. */
const PENDING_LABEL = "Подготвя се чернова…";

export interface TodayStoryActionsProps {
  storyId: string;
  href: string;
  /** Canonical triage intents. The backend decides; nothing is derived here. */
  actions: readonly string[];
  quickDraft: { available: boolean; label: string } | undefined;
  busy: boolean;
  blocked: boolean;
  onIgnore: () => void;
  onQuickDraft: () => void;
  ignoreDisabled: boolean;
}

/**
 * V1.2-D2 §24/§25, restated for G1 §16/§17: exactly three triage intents.
 *
 * `Чернова` is the only filled control — the one forward action the whole screen
 * is built to make obvious. `Прегледай` is the ordinary navigation link to the
 * Story it has always been. `Игнорирай` is deliberately the quietest: it is a
 * routine, fully reversible triage move, so it gets no destructive red.
 *
 * §17: while a Quick Draft runs, the entire action area becomes one calm inline
 * status. The backend is doing research, opening sources and generating; none of
 * that is the editor's business, so exactly one sentence is shown. No modal, no
 * wizard, and no stage vocabulary — the editor asked for one thing.
 */
export function TodayStoryActions({
  storyId,
  href,
  actions,
  quickDraft,
  busy,
  blocked,
  onIgnore,
  onQuickDraft,
  ignoreDisabled,
}: TodayStoryActionsProps) {
  // §4/§43: the backend is the authority. A row carrying no triage state at all
  // (an older cached projection) still renders and simply offers no `Чернова` —
  // the editor is never shown a button the backend did not grant.
  const canQuick = actions.includes("QUICK_DRAFT") && quickDraft?.available === true;
  const canIgnore = actions.includes("IGNORE");

  if (busy) {
    return (
      <div className={styles.actions} data-triage-state="pending">
        {/*
          A small spinner plus the single status sentence. The control stays a
          real disabled button so the pending state is unreachable by click and
          keyboard alike, and so it occupies exactly the action region the
          buttons it replaces occupied. The spinner is decorative; the sentence
          is the whole message and the whole accessible name.
        */}
        <button className={styles.pending} type="button" disabled>
          <span className={styles.spinner} aria-hidden="true" />
          {PENDING_LABEL}
        </button>
      </div>
    );
  }

  return (
    <div className={styles.actions}>
      {/*
        §21: while a blocker is showing, the two command buttons step aside so the
        row states one thing at a time. `Прегледай` always remains — §19 makes it
        the action for a blocked Story.
      */}
      {!blocked && canIgnore ? (
        <button
          className={styles.quiet}
          type="button"
          disabled={ignoreDisabled}
          onClick={onIgnore}
          data-ignore-story={storyId}
        >
          Игнорирай
        </button>
      ) : null}
      <Link className={styles.secondary} to={href} data-review-story={storyId}>
        Прегледай
      </Link>
      {!blocked && canQuick ? (
        <button
          className={styles.action}
          type="button"
          onClick={onQuickDraft}
          data-quick-draft={storyId}
        >
          {quickDraft?.label ?? "Чернова"}
        </button>
      ) : null}
    </div>
  );
}
