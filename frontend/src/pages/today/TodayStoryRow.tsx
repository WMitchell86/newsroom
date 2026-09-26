import { Link } from "react-router-dom";
import {
  formatRelativeTime,
  isRedundantSummary,
  publisherCountLabel,
} from "../../shared/editorLabels";
import { TodayBlocker } from "./TodayBlocker";
import { TodayStoryActions } from "./TodayStoryActions";
import type { TodayStoryRow } from "./todayView";
import styles from "./Today.module.css";

/** §14: `1 ново развитие` / `2 нови развития` — the real delta, in words. */
function developmentCount(count: number): string {
  if (count <= 1) return "1 ново развитие";
  return `${count} нови развития`;
}

export interface TodayStoryRowProps {
  row: TodayStoryRow;
  href: string;
  /** The backend's own explanation, or `null` when there is nothing blocked. */
  blocker: string | null;
  busy: boolean;
  ignoreDisabled: boolean;
  onIgnore: () => void;
  onQuickDraft: () => void;
  now?: Date;
}

/**
 * V1.2-G1 §12: one Story as a newsroom wire row.
 *
 * Thin divider, serif headline, one compact sans-serif metadata line, a
 * restrained summary, and the three triage actions aligned to the right. No
 * enclosing rounded card: a desk of rows reads faster than a wall of tiles, and
 * cards would push the density the editor needs down the screen.
 */
export function TodayStoryRowView({
  row,
  href,
  blocker,
  busy,
  ignoreDisabled,
  onIgnore,
  onQuickDraft,
  now,
}: TodayStoryRowProps) {
  const sources = publisherCountLabel(row.publisherCount);
  // §14: never print the headline twice. A summary that is the title with
  // different punctuation is not new information and only makes the row look
  // padded, so the line is simply not rendered.
  const summary =
    row.summary && !isRedundantSummary(row.title, row.summary) ? row.summary : null;

  return (
    <li className={styles.storyRow} data-story-row={row.objectId}>
      {/*
        §13: the category label slot. It is rendered ONLY from real category
        data. Today has none — `category` is not part of the canonical Story
        schema — so on real rows this renders nothing at all, and no empty
        placeholder is left behind. The visual contract is reserved here so the
        category slice can switch it on without relaying out the row.
      */}
      {row.category ? <p className={styles.categoryLabel}>{row.category}</p> : null}

      <div className={styles.storyBody}>
        <h3 className={styles.headline}>
          <Link to={href}>{row.title}</Link>
        </h3>
        <p className={styles.storyMeta}>
          {/*
            §14: editor-useful metadata only. Locality is deliberately absent —
            it is not canonical yet, and parsing a place name out of a headline
            in React would be inventing data. The source count is corroboration
            context, never a claim that those pages were opened (§15/§20).
          */}
          {row.reason === "NEW_STORY" ? <span>Нова история</span> : null}
          {row.reason === "UNREVIEWED_DEVELOPMENT" ? (
            <span>{developmentCount(row.delta.unreviewedDevelopmentCount)}</span>
          ) : null}
          {sources ? <span>{sources}</span> : null}
          <span>{formatRelativeTime(row.timestamp, now)}</span>
        </p>
        {summary ? <p className={styles.storySummary}>{summary}</p> : null}
      </div>

      <div className={styles.storyAside}>
        {/*
          §21: the warning occupies the same horizontal action region as the
          buttons it replaces, so a blocked row does not grow and push the rest
          of the desk down.
        */}
        {blocker ? <TodayBlocker message={blocker} /> : null}
        {/*
          §19: a blocker always keeps the way out. `Прегледай` survives it, because
          opening the Story is precisely how the editor investigates the gap the
          blocker describes — the two are alternatives, not rivals. The two
          command buttons yield to the warning so the row shows one thing.
        */}
        <TodayStoryActions
          storyId={row.objectId}
          href={href}
          actions={row.availableActions ?? []}
          quickDraft={row.quickDraft}
          busy={busy}
          blocked={blocker !== null}
          ignoreDisabled={ignoreDisabled}
          onIgnore={onIgnore}
          onQuickDraft={onQuickDraft}
        />
      </div>
    </li>
  );
}
