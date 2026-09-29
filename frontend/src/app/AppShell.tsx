import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { getOperations } from "../api/client";
import type { OperationSummary } from "../api/dto";
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
/**
 * V1.2-G4.12 — "it is ready", even if you never opened the page.
 *
 * The G4.11 strip answers "is anything happening". It cannot answer "is it
 * done", and that is the question an editor actually has after pressing a
 * button and walking away: they went to Stories, and the only way to learn
 * the draft had landed was to go back and look.
 *
 * Two deliberate constraints:
 *
 * - **Only a transition, never a backlog.** Work that finished before this
 *   page opened produces nothing. A page that greets you with "3 drafts ready"
 *   from last night is a backlog, not a notification — the editor has a list.
 * - **Only while you are elsewhere.** The moment the editor is on the Article,
 *   the Article page shows its own state; announcing it there would be
 *   announcing news they are looking straight at.
 */
interface ReadyNotice {
  token: string;
  href: string;
  label: string;
}

/** Where a finished operation actually lives, derived from its own scope id. */
function destinationFor(storyId: string): { href: string; label: string } | null {
  const draft = /^article-draft:(art_[a-z0-9]+(?:_[0-9]+)?)$/.exec(storyId);
  if (draft?.[1]) return { href: `/articles/${draft[1]}`, label: "Черновата е готова" };
  if (storyId === "today-refresh") return { href: "/", label: "Новините са обновени" };
  if (/^s[a-zA-Z0-9_-]+$/.test(storyId)) {
    return { href: `/stories/${storyId}`, label: "Историята е готова" };
  }
  return null;
}

function useReadyNotices(rows: unknown, pathname: string) {
  const seenRunning = useRef<Set<string>>(new Set());
  const dismissed = useRef<Set<string>>(new Set());
  const [notices, setNotices] = useState<ReadyNotice[]>([]);
  const list = Array.isArray(rows) ? rows : [];

  useEffect(() => {
    for (const op of list) {
      if (op.status === "running" || op.status === "pending") {
        seenRunning.current.add(op.operationToken);
      }
    }
    setNotices((prev) => {
      const known = new Set(prev.map((n) => n.token));
      const fresh: ReadyNotice[] = [];
      for (const op of list) {
        if (op.status !== "succeeded") continue;
        if (!seenRunning.current.has(op.operationToken)) continue;
        if (dismissed.current.has(op.operationToken)) continue;
        if (known.has(op.operationToken)) continue;
        const where = destinationFor(op.storyId);
        if (!where) continue;
        known.add(op.operationToken);
        fresh.push({ token: op.operationToken, ...where });
      }
      return fresh.length ? [...prev, ...fresh] : prev;
    });
  }, [list]);

  const dismiss = (token: string) => {
    // Remembered beyond the click: the operation is still `succeeded` on every
    // poll, so without this it would come straight back.
    dismissed.current.add(token);
    setNotices((prev) => prev.filter((n) => n.token !== token));
  };

  return { notices: notices.filter((n) => n.href !== pathname), dismiss };
}

function ReadyBanner({
  notices,
  onDismiss,
}: {
  notices: ReadyNotice[];
  onDismiss: (token: string) => void;
}) {
  if (!notices.length) return null;
  return (
    <div className={styles.ready ?? ""} role="status" data-ready="yes">
      <span className={styles.readyDot ?? ""} aria-hidden="true" />
      <ul className={styles.readyList ?? ""}>
        {notices.map((n) => (
          <li key={n.token} className={styles.readyItem ?? ""}>
            <Link
              className={styles.readyLink ?? ""}
              to={n.href}
              onClick={() => onDismiss(n.token)}
            >
              {n.label}
            </Link>
            <button
              className={styles.readyDismiss ?? ""}
              type="button"
              aria-label={`Скрий: ${n.label}`}
              onClick={() => onDismiss(n.token)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ActivityStrip({ active }: { active: OperationSummary[] }) {
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

/** One poll, two surfaces: what is running, and what just finished. */
function ShellActivity() {
  const location = useLocation();
  const operations = useQuery({
    queryKey: ["operations"],
    queryFn: getOperations,
    refetchInterval: 3_000,
    retry: false,
  });
  // Defensive on purpose, and it belongs HERE: this lives in the shell above
  // every page, so a shape it did not expect would take the whole application
  // down. The first version called `.filter` on a `{}` and unmounted the
  // editor's entire desk. Anything unrecognised is "nothing running".
  const rows = operations.data?.operations;
  const list = Array.isArray(rows) ? rows : [];
  const active = list.filter((op) => op.status === "running" || op.status === "pending");
  const { notices, dismiss } = useReadyNotices(rows, location.pathname);
  return (
    <>
      <ReadyBanner notices={notices} onDismiss={dismiss} />
      <ActivityStrip active={active} />
    </>
  );
}

export function AppShell() {
  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.main}>
        <ShellActivity />
        <RouteOutlet />
      </main>
    </div>
  );
}
