import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { getOperations } from "../api/client";
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
// §1 freezes the rail to five primary destinations plus Настройки, and
// `Източници` was explicitly refused as a sixth. `Операции` is NOT promoted
// into that frozen set: the rail is where the editor's daily destinations
// live, and an operations log is a diagnostic, not one of them. It is reached
// from Today and from Настройки instead.
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

export function PrimaryNavigation({ todayHref = "/" }: { todayHref?: string } = {}) {
  return (
    <nav className={styles.navigation} aria-label="Основни раздели">
      <ul className={styles.list}>
        {editorialAreas.map((area) => (
          <li className={styles.item} key={area.to}>
            {area.to === "/" ? (
              <RailLink {...area} to={todayHref} />
            ) : (
              <RailLink {...area} />
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}

/**
 * V1.2-G4.11 — the rail's «Днес» must come back to the desk you left.
 *
 * Moving the view into the URL was not enough on its own. Clicking «Днес» in
 * the rail navigated to a bare `/`, which dropped `?tab=new&sort=publishers`
 * on the floor — the editor left the desk, came back, and got a different one
 * with the same address bar. The parameters have to travel WITH the link.
 *
 * They are remembered for the browser session, not forever: a desk the editor
 * deliberately rearranged an hour ago is not what they want when they next
 * open the product, and a stale "view" that silently overrides a shared link
 * would be worse than a reset.
 */
const TODAY_VIEW_KEY = "newsroom.today.view";

function readRememberedTodayView(): string {
  try {
    return window.sessionStorage.getItem(TODAY_VIEW_KEY) ?? "";
  } catch {
    // Private mode and blocked storage are ordinary, not an error worth a
    // broken rail: the link simply falls back to a clean desk.
    return "";
  }
}

export function Sidebar() {
  const location = useLocation();
  const [todayHref, setTodayHref] = useState("/");
  // Re-read on every navigation, so the link is correct the moment the editor
  // moves away from Today rather than only on the next full render.
  useEffect(() => {
    setTodayHref(location.pathname === "/" ? location.search : readRememberedTodayView());
  }, [location.pathname, location.search]);

  return (
    <aside className={styles.rail}>
      <div className={styles.brandBlock}>
        <NavLink to={todayHref || "/"} className={styles.brand ?? ""}>
          Редакция
        </NavLink>
        <p className={styles.brandNote}>Редакционно бюро</p>
      </div>

      <PrimaryNavigation todayHref={todayHref || "/"} />

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

/**
 * V1.2-G4.11 — what is running, on every page.
 *
 * The editor pressed «Направи чернова», walked to Stories, came back and could
 * not tell whether anything was happening: the Operations log existed but was
 * reachable only from a link inside the Today header. Moving between pages
 * made the work invisible, which is what "I do not know what is going on"
 * actually means.
 *
 * This is a strip, deliberately NOT a sixth rail item. §1 freezes the rail to
 * five destinations and `Операции` was explicitly refused as a sixth; a
 * status line above the page is a different thing, and adding a destination
 * to solve a visibility problem would break a contract for no reason.
 *
 * It shows only unfinished work, and only when there is some. A permanent
 * "0 running" badge trains the eye to skip the one place status is shown.
 */
function ActivityStrip() {
  const operations = useQuery({
    queryKey: ["operations"],
    queryFn: getOperations,
    refetchInterval: 3_000,
    retry: false,
  });
  // Defensive on purpose. This strip lives in the SHELL, above every page, so
  // a shape it did not expect would take the whole application down with it —
  // a status line must never be able to break the product it reports on. The
  // first version called `.filter` on the response and a `{}` from one failed
  // poll unmounted the editor's entire desk.
  const rows = operations.data?.operations;
  const active = Array.isArray(rows)
    ? rows.filter((op) => op.status === "running" || op.status === "pending")
    : [];
  if (!active.length) return null;
  return (
    <div className={styles.activity ?? ""} role="status" data-activity="active">
      <span className={styles.activityDot ?? ""} aria-hidden="true" />
      <span className={styles.activityText ?? ""}>
        {active.length === 1 ? "В момента върви" : "В момента вървят"}:{" "}
        {active.map((op) => op.storyId).join(", ")}
      </span>
      <Link className={styles.activityLink ?? ""} to="/operations">
        Подробности
      </Link>
    </div>
  );
}

export function AppShell() {
  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.main}>
        <ActivityStrip />
        <RouteOutlet />
      </main>
    </div>
  );
}
