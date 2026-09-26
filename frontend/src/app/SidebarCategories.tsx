import { useId } from "react";
import styles from "./AppShell.module.css";

/**
 * V1.2-G1 §5: the category rail, prepared but not faked.
 *
 * The owner wants categories in the left column. Current Stories do **not** have
 * production editorial categories — `locality`/`category` are not part of the
 * canonical Story schema. So this component renders the *space* the taxonomy will
 * occupy and refuses to pretend the space is already populated.
 *
 * What it deliberately does NOT do, because each of these would manufacture
 * product state the backend cannot support:
 *
 *   * no title keyword matching,
 *   * no "infer the category from the source kind",
 *   * no archive/category inference,
 *   * no shadow-model category output,
 *   * no fabricated per-category counts,
 *   * no loud `СКОРО` badge on every row.
 *
 * `Всички` is the one real state and is genuinely active. Everything else is
 * rendered as a **disabled** control with an accessible description, so the
 * editor sees where the taxonomy goes without being able to click a filter that
 * would silently return the same unfiltered set. `data-category-state` is the
 * seam the category slice flips: activate an entry, and nothing in the rail's
 * structure has to change.
 */
const futureCategories = [
  "Общество",
  "Култура",
  "Туризъм",
  "Бизнес",
  "Спорт",
  "Образование",
  "Здраве",
  "Инфраструктура",
  "Други",
] as const;

/** The one accessible sentence that explains the whole prepared rail. */
export const categoryRailHint = "Категоризацията предстои";

export function SidebarCategories() {
  const headingId = useId();
  const hintId = useId();
  return (
    <section className={styles.categories} aria-labelledby={headingId}>
      <h2 className={styles.railHeading} id={headingId}>
        Категории
      </h2>
      <ul className={styles.categoryList}>
        <li className={styles.categoryItem}>
          {/*
            `Всички` is a real, active control, not a disabled placeholder: it is
            the truthful description of the unfiltered set the backend returns.
          */}
          <span
            className={`${styles.categoryLink} ${styles.categoryActive}`}
            aria-current="true"
            data-category-state="active"
          >
            Всички
          </span>
        </li>
        {futureCategories.map((label) => (
          <li className={styles.categoryItem} key={label}>
            {/*
              A real disabled <button>, not a styled <div>: it is exposed as
              disabled to assistive technology, it is not focusable, and it
              cannot fire a handler — which is what "not yet backed by data"
              has to mean. The `aria-describedby` carries the reason, so the
              explanation is available without hovering.
            */}
            <button
              className={styles.categoryLink}
              type="button"
              disabled
              aria-describedby={hintId}
              data-category-state="preparatory"
            >
              {label}
            </button>
          </li>
        ))}
      </ul>
      <p className={styles.railHint} id={hintId}>
        {categoryRailHint}
      </p>
    </section>
  );
}