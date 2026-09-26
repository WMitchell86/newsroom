import { todaySorts, todayTabs, type TodaySort, type TodayTab } from "./todayView";
import styles from "./Today.module.css";

export interface TodayToolbarProps {
  tab: TodayTab;
  onTabChange: (tab: TodayTab) => void;
  counts: Record<TodayTab, number>;
  sort: TodaySort;
  onSortChange: (sort: TodaySort) => void;
  shownCount: number;
}

/**
 * V1.2-G1 §9/§22: one compact line — attention groups on the left, sorting on
 * the right.
 *
 * The owner explicitly misses easy sorting, so the control is visible and
 * labelled rather than hidden behind an overflow menu. It is a single toolbar:
 * search lives in the header (§6) and is not repeated here.
 *
 * The tab counts are the real group sizes from the projection, and each tab maps
 * to a group the backend already returns. There is no fourth "requires
 * attention" tab, because Today has no such field and inventing one would be a
 * status the editor could misread.
 */
export function TodayToolbar({
  tab,
  onTabChange,
  counts,
  sort,
  onSortChange,
  shownCount,
}: TodayToolbarProps) {
  return (
    <div className={styles.toolbar}>
      <div className={styles.tabs} role="group" aria-label="Групи днешни истории">
        {todayTabs.map((option) => (
          <button
            key={option.value}
            className={`${styles.tab}${tab === option.value ? ` ${styles.tabActive}` : ""}`}
            type="button"
            aria-pressed={tab === option.value}
            onClick={() => onTabChange(option.value)}
          >
            {option.label}
            <span className={styles.tabCount}> ({counts[option.value]})</span>
          </button>
        ))}
      </div>
      <div className={styles.sortField}>
        {/*
          §9: only the two orderings this slice can support truthfully. There is
          deliberately no "Топ" / "Най-важни" / AI ranking — those require ranking
          work that does not exist, and a ranking the editor cannot explain is
          worse than no ranking at all.
        */}
        <label className={styles.sortLabel} htmlFor="today-sort">
          Сортирай
        </label>
        <select
          id="today-sort"
          className={styles.sortSelect}
          value={sort}
          onChange={(event) => onSortChange(event.target.value as TodaySort)}
        >
          {todaySorts.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <span className={styles.shownCount}>
          {shownCount} {shownCount === 1 ? "история" : "истории"}
        </span>
      </div>
    </div>
  );
}
