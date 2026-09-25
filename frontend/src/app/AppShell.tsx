import { NavLink, Outlet } from "react-router-dom";
import styles from "./AppShell.module.css";

const areas = [
  { to: "/", label: "Днес", end: true },
  { to: "/stories", label: "Истории", end: false },
  { to: "/articles", label: "Статии", end: false },
  { to: "/archive", label: "Архив", end: false },
  { to: "/settings", label: "Настройки", end: true },
] as const;

export function TopNavigation() {
  return <header className={styles.header}>
    <div className={styles.inner}>
      <NavLink to="/" className={styles.brand ?? ""}>Редакция</NavLink>
      <nav className={styles.navigation} aria-label="Основни раздели">
        <ul className={styles.list}>
          {areas.map((area) => <li className={styles.item} key={area.to}>
            <NavLink
              to={area.to}
              end={area.end}
              className={({ isActive }) => `${styles.link ?? ""}${isActive ? ` ${styles.active ?? ""}` : ""}`}
            >
              {area.label}
            </NavLink>
          </li>)}
        </ul>
      </nav>
    </div>
  </header>;
}

export function RouteOutlet() {
  return <Outlet />;
}

export function AppShell() {
  return <>
    <TopNavigation />
    <main className={styles.main}><RouteOutlet /></main>
  </>;
}
