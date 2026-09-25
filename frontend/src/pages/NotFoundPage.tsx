import { Link } from "react-router-dom";
import { PageHeader } from "../shared/EditorPrimitives";
import styles from "./SupportingPages.module.css";

export function NotFoundPage() {
  return <div className={`${styles.page} ${styles.notFound}`}>
    <PageHeader
      kicker="Грешка 404"
      title="Страницата не е намерена"
      lede="Проверете адреса или се върнете към началната страница."
    />
    <Link className={styles.backLink} to="/">Към началото</Link>
  </div>;
}
