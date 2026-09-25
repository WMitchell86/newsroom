import { PageHeader } from "../shared/EditorPrimitives";
import styles from "./SupportingPages.module.css";

const settingsEntries = [
  {
    to: "/settings/sources",
    title: "Източници",
    description: "Настройки на източниците и начина на събиране на материали.",
  },
  {
    to: "/settings/ai",
    title: "AI и разходи",
    description: "Модели, квоти, платени и безплатни настройки и видимост на разходите.",
  },
  {
    to: "/settings/inputs",
    title: "Канали за вход",
    description: "Входни канали и интеграции, включително YouTube.",
  },
  {
    to: "/settings/system",
    title: "Система",
    description: "Технически настройки и диагностика на системата.",
  },
] as const;

export function SettingsLanding() {
  return <div className={styles.page}>
    <PageHeader
      kicker="Технически настройки"
      title="Настройки"
      lede="Отделни технически настройки, които не са част от ежедневната редакционна работа."
    />
    <p className={styles.settingsNote}>
      Тези четири бъдещи подраздела са запазени като навигационни точки. Съдържанието им още не е внедрено.
    </p>
    <div className={styles.settingsList} aria-label="Технически настройки">
      <ul>
      {settingsEntries.map((entry) => <li
        className={styles.settingsRow}
        key={entry.to}
        aria-disabled="true"
      >
        <span>
          <span className={styles.settingsTitle}>{entry.title}</span>
          <span className={styles.settingsDescription}>{entry.description}</span>
        </span>
        <span className={styles.settingsAvailability}>Още не е налично</span>
      </li>)}
      </ul>
    </div>
  </div>;
}
