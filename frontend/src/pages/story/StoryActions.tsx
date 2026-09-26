import type { AvailableAction } from "../../api/dto";
import { headerPrimaryAction } from "./storyView";
import styles from "./Story.module.css";

export interface StoryCommands {
  /** True while any canonical Story command is in flight. */
  pending: boolean;
  reviewPending: boolean;
  followPending: boolean;
  unfollowPending: boolean;
  ignorePending: boolean;
  startPending: boolean;
  /** The backend's own sentence for a failed command, or `null`. */
  error: string | null;
  onReview(): void;
  onFollow(): void;
  onUnfollow(): void;
  onIgnore(): void;
  onStartArticle(): void;
}

export interface StoryActionsProps {
  actions: readonly AvailableAction[];
  commands: StoryCommands;
  /** The offered action this page shows as its one strong forward move. */
  primary: ReturnType<typeof headerPrimaryAction>;
}

/**
 * V1.2-G2 §5/§7/§23/§29: the current editorial actions, and only those.
 *
 * The backend decides what exists: this component renders one control per entry
 * in `availableActions` and never reconstructs a permission, never shows an
 * action because it is conceptually available, and never hides a failure by
 * dropping the control.
 *
 * At most one of them is filled. `Започни статия` is the filled forward move
 * only when it is genuinely the next step — no Story Article yet and no research
 * round to run first. When a Story already has an Article, or when the missing
 * information is what the editor has to resolve first, it stays outlined: the
 * Article block and the research control own those decisions.
 *
 * `Следи` is deliberately the quietest thing in the row and is set apart by a
 * hairline. Following a Story is a bookmark, not a workflow status, so it never
 * becomes a coloured banner and never competes with the forward action.
 *
 * Nothing is rendered at all when the projection offers nothing — an empty
 * action bar is chrome for its own sake.
 */
export function StoryActions({ actions, commands, primary }: StoryActionsProps) {
  const offered = (action: AvailableAction) => actions.includes(action);
  const busy = commands.pending;
  const canStart = offered("START_ARTICLE");
  const anyAction =
    canStart || offered("REVIEW") || offered("IGNORE") || offered("FOLLOW") || offered("UNFOLLOW");
  if (!anyAction) return null;

  return (
    <>
      <div
        className={styles.actionCluster}
        aria-label="Действия за историята"
        aria-busy={busy}
      >
        {canStart ? (
          <span className={styles.actionControl}>
            <button
              className={primary === "START_ARTICLE" ? styles.primary : styles.secondary}
              type="button"
              disabled={busy}
              onClick={commands.onStartArticle}
              data-story-action="start-article"
            >
              {commands.startPending ? "Започва се…" : "Започни статия"}
            </button>
          </span>
        ) : null}

        {offered("REVIEW") ? (
          <span className={styles.actionControl}>
            <button
              className={styles.quiet}
              type="button"
              disabled={busy}
              onClick={commands.onReview}
            >
              {commands.reviewPending ? "Преглежда се…" : "Прегледай"}
            </button>
          </span>
        ) : null}

        {offered("IGNORE") ? (
          <span className={styles.actionControl}>
            <button
              className={styles.quiet}
              type="button"
              disabled={busy}
              onClick={commands.onIgnore}
            >
              {commands.ignorePending ? "Игнорира се…" : "Игнорирай"}
            </button>
          </span>
        ) : null}

        {offered("FOLLOW") ? (
          <span className={styles.followControl}>
            <button
              className={styles.quiet}
              type="button"
              disabled={busy}
              onClick={commands.onFollow}
            >
              {commands.followPending ? "Следи се…" : "Следи"}
            </button>
          </span>
        ) : null}

        {offered("UNFOLLOW") ? (
          <span className={styles.followControl}>
            <button
              className={styles.quiet}
              type="button"
              disabled={busy}
              onClick={commands.onUnfollow}
            >
              {commands.unfollowPending ? "Следването се прекратява…" : "Спри следването"}
            </button>
          </span>
        ) : null}
      </div>

      {/* §17: a failed command says what the backend said and leaves every
          other control in place, so the editor can try the next thing. */}
      {commands.error ? (
        <p className={styles.actionError} role="alert">
          {commands.error}
        </p>
      ) : null}
    </>
  );
}
