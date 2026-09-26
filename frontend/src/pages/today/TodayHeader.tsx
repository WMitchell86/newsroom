import styles from "./Today.module.css";

export interface TodayHeaderProps {
  /** The D1 projection, for the refresh context. */
  lastRefreshText: string;
  onRefresh: () => void;
  refreshPending: boolean;
  refreshError: string | null;
  query: string;
  onQueryChange: (value: string) => void;
}

/**
 * V1.2-G1 §7: the header, deliberately short.
 *
 * The editor needs three things here and nothing else: what this screen is, how
 * current it is, and one obvious way to change what it shows. The refresh
 * context is the existing D1 `lastRefresh` projection rendered in
 * Europe/Sofia — never a raw UTC instant — and it occupies less vertical space
 * than the previous implementation so the Story list starts higher.
 */
export function TodayHeader({
  lastRefreshText,
  onRefresh,
  refreshPending,
  refreshError,
  query,
  onQueryChange,
}: TodayHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.headerTop}>
        <div>
          <h1 className={styles.title}>Днес</h1>
          <p className={styles.lede}>
            Нови публикации и развития, които изискват редакционна преценка.
          </p>
        </div>
        <div className={styles.refreshArea}>
          {/*
            §6: the search field sits high, in the header, and is scoped to what
            the Today projection actually carries. The placeholder says exactly
            that, so the editor is never led to believe this is archive-wide.
          */}
          <div className={styles.searchField}>
            <label className={styles.searchLabel} htmlFor="today-search">
              Търсене в днешните истории
            </label>
            <input
              id="today-search"
              className={styles.searchInput}
              type="search"
              value={query}
              maxLength={200}
              placeholder="Търси в истории, източници и заглавия…"
              onChange={(event) => onQueryChange(event.target.value)}
            />
          </div>
          <div className={styles.refreshControl}>
            <button
              className={styles.refresh}
              type="button"
              disabled={refreshPending}
              onClick={onRefresh}
              data-refresh-trigger="newsroom"
            >
              {refreshPending ? "Обновява се…" : "Обнови"}
            </button>
            {refreshPending ? (
              <span className={styles.refreshStatus} role="status" aria-live="polite">
                Обновява се.
              </span>
            ) : null}
            {refreshError ? (
              <span className={styles.refreshError} role="alert">
                {refreshError}
              </span>
            ) : null}
          </div>
        </div>
      </div>
      <p className={styles.refreshMeta}>{lastRefreshText}</p>
    </header>
  );
}
