import type { TodayScope } from "../../api/dto";
import {
  todayScopes,
  todaySorts,
  todayTabs,
  type TodaySort,
  type TodayTab,
} from "./todayView";
import styles from "./Today.module.css";

export interface TodayToolbarProps {
  tab: TodayTab;
  onTabChange: (tab: TodayTab) => void;
  counts: Record<TodayTab, number>;
  sort: TodaySort;
  onSortChange: (sort: TodaySort) => void;
  shownCount: number;
  scope: TodayScope;
  onScopeChange: (scope: TodayScope) => void;
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
  scope,
  onScopeChange,
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
      {/*
        V1.2-G4.1 §A4: one quiet control, two positions, default `Регионът`.
        It is a scope switch and not a filter: the server decides which Stories
        are regional, and «Истории» always reaches every collected Story, so
        nothing here hides work — it only changes which desk is being read.
      */}
      <div className={styles.tabs} role="group" aria-label="Обхват на днешния работен екран" data-today-scope-active={scope}>
        {todayScopes.map((option) => (
          <button
            key={option.value}
            className={`${styles.tab}${scope === option.value ? ` ${styles.tabActive}` : ""}`}
            type="button"
            /* The pressed state is the editor's OWN selection, never the
               projection's echo: the control must show the choice that was made
               even while the refetch for it is still in flight. */
            aria-pressed={scope === option.value}
            data-today-scope={option.value}
            onClick={() => onScopeChange(option.value)}
          >
            {option.label}
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
