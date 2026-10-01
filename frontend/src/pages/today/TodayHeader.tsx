import { Link } from "react-router-dom";
import type { DeskDraftReport } from "../../api/client";
import type { RoleHealth } from "../../api/dto";
import styles from "./Today.module.css";

/**
 * V1.2-G4.5: can the system actually work right now?
 *
 * The grouping notice below already told the editor that story merging was
 * limited, and said nothing about WHY. On 2026-09-28 that was because every
 * route of the `story` role was marked EXHAUSTED while all seven models were
 * present in their provider catalogues - a wrong mark, sitting there for a day.
 * This badge names the cause and the one command that clears it.
 *
 * It is quiet when everything is fine, on purpose: a permanently visible warning
 * is a warning the editor learns to ignore, which is how a red badge for a day
 * became invisible.
 */
function RoleHealthBadge({
  health,
}: {
  health: { ok: boolean; roles: RoleHealth[]; unroutableRoles: string[]; remedy: string } | null | undefined;
}) {
  // Fail-safe, deliberately. A payload without the field is not a healthy
  // system and not a broken one — it is an older or unexpected one — and the
  // desk must still render. `Array.isArray` rather than a truthy check because
  // `unroutableRoles: undefined` is exactly what a stale cache looks like, and
  // `.length` on it must never take the whole page down.
  if (!health || !Array.isArray(health.unroutableRoles)) return null;
  const dead = health.unroutableRoles;
  if (!dead.length) {
    return (
      <p className={styles.roleHealthOk} data-role-health="ok">
        ✓ всички роли имат достъпен маршрут
      </p>
    );
  }
  return (
    <p className={styles.roleHealthBad} role="status" data-role-health="blocked">
      ⚠ {dead.join(", ")} няма достъпен маршрут — тези функции работят намалено.{" "}
      <code>{health.remedy}</code>
    </p>
  );
}

export interface TodayHeaderProps {
  /** The D1 projection, for the refresh context. */
  lastRefreshText: string;
  onRefresh: () => void;
  refreshPending: boolean;
  refreshError: string | null;
  query: string;
  onQueryChange: (value: string) => void;
  /**
   * V1.2-G4.5. Whether the system can actually work right now, per role.
   * `null` while unknown — an unknown state is not a warning.
   */
  roleHealth?: { ok: boolean; roles: RoleHealth[]; unroutableRoles: string[]; remedy: string } | null;
  /**
   * V1.2-G4.40. The desk-level press. `null` after a run that returned nothing
   * usable, so the report line is only rendered when there is one.
   */
  onDraftDesk: () => void;
  draftDeskPending: boolean;
  draftDeskError: string | null;
  draftDeskReport: DeskDraftReport | null;
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
  roleHealth,
  onDraftDesk,
  draftDeskPending,
  draftDeskError,
  draftDeskReport,
}: TodayHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.headerTop}>
        <div>
          <h1 className={styles.title}>Днес</h1>
          <p className={styles.lede}>
            Нови публикации и развития, които изискват редакционна преценка.
          </p>
          {/*
            V1.2-G4.6. The editor starts work from THIS screen, and until the
            operations page existed there was nowhere to go afterwards to learn
            what became of it. The link sits next to the button they press, not
            in a rail that §1 keeps frozen at five destinations.
          */}
          <Link className={styles.operationsLink} to="/operations">
            Какво става с поръчаните чернови →
          </Link>
          <RoleHealthBadge health={roleHealth} />
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
          {/*
            V1.2-G4.40 «Направи чернови». The desk press, next to the refresh it
            depends on, because until it existed the Quick Draft pipeline could
            only be run one Story at a time - and the desk is where the editor
            sees the Stories that need it. The caption states what came back
            from the server's own report; the CAP is deliberately not printed
            before the press, because it is the server's number and the client
            must not restate it as if it were its own.
          */}
          <div className={styles.refreshControl}>
            <button
              className={styles.refresh}
              type="button"
              disabled={draftDeskPending || refreshPending}
              onClick={onDraftDesk}
              data-desk-draft-trigger="desk"
            >
              {draftDeskPending ? "Пишат се чернови…" : "Направи чернови"}
            </button>
            {draftDeskPending ? (
              <span className={styles.refreshStatus} role="status" aria-live="polite">
                Върви по историите, една след друга. Може да отнеме минути.
              </span>
            ) : null}
            {draftDeskReport ? (
              <span className={styles.refreshStatus} role="status">
                Готови {draftDeskReport.created} от {draftDeskReport.attempted} (до{" "}
                {draftDeskReport.limit}). Останалите са на опашката за следващото
                натискане.
              </span>
            ) : null}
            {draftDeskError ? (
              <span className={styles.refreshError} role="alert">
                {draftDeskError}
              </span>
            ) : null}
          </div>
        </div>
      </div>
      <p className={styles.refreshMeta}>{lastRefreshText}</p>
    </header>
  );
}
