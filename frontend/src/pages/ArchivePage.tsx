import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { archiveOptions } from "../api/queries";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../shared/EditorPrimitives";
import { formatDate } from "../shared/editorLabels";
import styles from "./SupportingPages.module.css";

export function ArchivePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryText = searchParams.get("q")?.trim() ?? "";
  const archive = useQuery(archiveOptions(queryText));
  const articles = archive.data?.articles ?? [];

  function updateSearch(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value.trim()) next.set("q", value);
    else next.delete("q");
    setSearchParams(next, { replace: true });
  }

  return <div className={styles.page}>
    <PageHeader
      kicker="Завършени редакционни материали"
      title="Архив"
      lede="Прегледайте финализираните статии и свързаните с тях истории."
    />

    <form className={styles.searchForm} role="search" onSubmit={(event) => event.preventDefault()}>
      <label className={styles.searchLabel} htmlFor="archive-search">Търсене в архива</label>
      <div className={styles.searchControls}>
        <input
          id="archive-search"
          className={styles.searchInput}
          type="search"
          value={queryText}
          maxLength={200}
          placeholder="Заглавие или история"
          onChange={(event) => updateSearch(event.target.value)}
        />
        <button className={styles.searchButton} type="submit">Търсене</button>
      </div>
    </form>

    {archive.isPending ? <LoadingState label="Зареждане на архива…" /> : null}
    {archive.isError ? <ErrorState error={archive.error} onRetry={() => void archive.refetch()} /> : null}
    {archive.isSuccess && articles.length === 0
      ? <EmptyState>{queryText ? "Няма архивирани статии, отговарящи на търсенето." : "Все още няма финализирани статии."}</EmptyState>
      : null}

    {archive.isSuccess && articles.length > 0
      ? <ul className={styles.archiveList}>
        {articles.map((article) => <li className={styles.archiveRow} key={article.id}>
          <h2 className={styles.archiveTitle}>
            <Link to={`/archive/${encodeURIComponent(article.id)}`}>{article.title}</Link>
          </h2>
          <p className={styles.archiveStory}>
            История:{" "}
            <Link to={`/stories/${encodeURIComponent(article.story.id)}`}>
              {article.story.title || "Свързана история"}
            </Link>
          </p>
          <p className={styles.archiveDate}>Финализирана на: {formatDate(article.finalizedAt)}</p>
        </li>)}
      </ul>
      : null}
  </div>;
}
