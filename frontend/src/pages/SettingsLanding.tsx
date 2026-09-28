import { Link } from "react-router-dom";
import { PageHeader } from "../shared/EditorPrimitives";
import styles from "./SupportingPages.module.css";

/**
 * V1.2-G4 §3: the secondary navigation under `Настройки`.
 *
 * V1.2-G4.6: `Операции` deliberately does NOT live here. §3 freezes this
 * landing to ONE entry, and an operations log is a diagnostic rather than a
 * setting. It is linked from Today instead - the screen the work starts on.
 *
 * `Източники` is the one screen this slice makes real, so it is a real link.
 * `AI и модели` and `Система` are deliberately **absent** rather than shipped as
 * empty tabs: §3 prefers one polished Sources screen over three half-built ones,
 * and a placeholder an editor can open teaches them that Settings is unfinished.
 */
const settingsEntries = [
  {
    to: "/settings/sources",
    title: "Източници",
    description: "Какво следим, кои източници приемаме за надеждни за факти и колко са важни.",
    available: true,
  },
] as const;

export function SettingsLanding() {
  return <div className={styles.page}>
    <PageHeader
      kicker="Настройки"
      title="Настройки"
      lede="Настройките, които определят какво следим и какво можем да използваме като факти."
    />
    <div className={styles.settingsList} aria-label="Настройки">
      <ul>
      {settingsEntries.map((entry) => <li key={entry.to}>
        <Link className={styles.settingsRow} to={entry.to}>
          <span>
            <span className={styles.settingsTitle}>{entry.title}</span>
            <span className={styles.settingsDescription}>{entry.description}</span>
          </span>
          {entry.available ? <span className={styles.settingsAvailability}>Отвори</span> : null}
        </Link>
      </li>)}
      </ul>
    </div>
  </div>;
}
