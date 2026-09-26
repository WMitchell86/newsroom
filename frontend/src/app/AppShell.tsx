import { NavLink, Outlet } from "react-router-dom";
import { SidebarCategories, categoryRailHint } from "./SidebarCategories";
import styles from "./AppShell.module.css";

/**
 * V1.2-G1 §1: the primary editor navigation is frozen.
 *
 * Five destinations, unchanged, in the same words. `Настройки` is the fifth and
 * stays in the left column, visually separated at the bottom of the rail from
 * the four everyday editorial destinations — not promoted to a header, not
 * moved to a top or right utility strip. `Източници` is deliberately absent:
 * it is not a primary editorial destination.
 */
const editorialAreas = [
  { to: "/", label: "Днес", end: true },
  { to: "/stories", label: "Истории", end: false },
  { to: "/articles", label: "Статии", end: false },
  { to: "/archive", label: "Архив", end: false },
] as const;

/** Separated from the everyday destinations by design, not by accident. */
const utilityAreas = [{ to: "/settings", label: "Настройки", end: true }] as const;

function RailLink({ to, label, end }: { to: string; label: string; end: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => `${styles.railLink ?? ""}${isActive ? ` ${styles.railActive ?? ""}` : ""}`}
    >
      {label}
    </NavLink>
  );
}

export function PrimaryNavigation() {
  return (
    <nav className={styles.navigation} aria-label="Основни раздели">
      <ul className={styles.list}>
        {editorialAreas.map((area) => (
          <li className={styles.item} key={area.to}>
            <RailLink {...area} />
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Sidebar() {
  return (
    <aside className={styles.rail}>
      <div className={styles.brandBlock}>
        <NavLink to="/" className={styles.brand ?? ""}>
          Редакция
        </NavLink>
        <p className={styles.brandNote}>Редакционно бюро</p>
      </div>

      <PrimaryNavigation />

      <SidebarCategories />

      <nav className={styles.utility} aria-label="Настройки">
        <ul className={styles.list}>
          {utilityAreas.map((area) => (
            <li className={styles.item} key={area.to}>
              <RailLink {...area} />
            </li>
          ))}
        </ul>
      </nav>
      <p className={styles.railNote}>{categoryRailHint}</p>
    </aside>
  );
}

export function RouteOutlet() {
  return <Outlet />;
}

export function AppShell() {
  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.main}>
        <RouteOutlet />
      </main>
    </div>
  );
}
