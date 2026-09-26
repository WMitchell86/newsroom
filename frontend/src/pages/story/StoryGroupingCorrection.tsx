import { useId, useState } from "react";
import type { StoryDetail } from "../../api/dto";
import styles from "./Story.module.css";

export interface StoryGroupingCorrectionProps {
  story: StoryDetail;
}

const correctionLabels: Record<string, string> = {
  DETACH_PUBLICATION: "Отдели публикация",
  MERGE_STORY: "Обедини с друга история",
};

/**
 * V1.2-G2 §25: the exceptional grouping corrections, at the bottom and closed.
 *
 * Detaching a publication or merging two Stories is a repair action an editor
 * takes when the *grouping itself* was wrong. It is not editorial work, and it
 * must never sit next to the forward action, the confirmed facts or the gaps.
 * So it lives in its own collapsed area at the foot of the page, in the quietest
 * possible treatment — outlined, not filled, and with no destructive red unless
 * a real destructive confirmation is ever required.
 *
 * The area renders only when the backend says a correction is available
 * (`correction.available`). Nothing is offered because the capability is
 * conceivable: the projection is the only authority, and when it offers nothing,
 * the page shows nothing.
 *
 * The controls are disabled with a plain explanation, exactly like the prepared
 * category rail in G1. The vocabulary exists in the canonical DTO, but no
 * canonical command implements it yet, and a live-looking button that does
 * nothing is worse than an honest one that says so.
 */
export function StoryGroupingCorrection({ story }: StoryGroupingCorrectionProps) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const correction = story.correction;
  if (!correction?.available || !correction.actions?.length) return null;

  return (
    <div className={styles.correctionArea}>
      <button
        className={styles.correctionToggle}
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "− Корекция на групирането" : "+ Корекция на групирането"}
      </button>
      <div id={bodyId} hidden={!open}>
        <div className={styles.correctionList}>
          {correction.actions.map((action) => (
            <button className={styles.correctionControl} type="button" key={action} disabled>
              {correctionLabels[action] ?? action}
            </button>
          ))}
        </div>
        <p className={styles.correctionNote}>
          Корекцията на групирането още не е налична. Тук не се променя нищо, докато не стане
          налична.
        </p>
      </div>
    </div>
  );
}
