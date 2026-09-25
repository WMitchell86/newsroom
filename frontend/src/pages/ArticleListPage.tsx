import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { articlesOptions } from "../api/queries";
import type { ArticleFilter } from "../api/client";
import { PageHeader, Context, EmptyState, ErrorState, LoadingState, StatusMarker } from "../shared/EditorPrimitives";
import { formatDate } from "../shared/editorLabels";
import ui from "../shared/ui.module.css";
import styles from "./ArticleWorkspace.module.css";

const filters: ReadonlyArray<{ value: ArticleFilter; label: string }> = [
  { value: "all", label: "Всички" },
  { value: "preparation", label: "Подготовка" },
  { value: "draft", label: "Чернова" },
  { value: "ready", label: "Готова" },
];

function isArticleFilter(value: string | null): value is ArticleFilter {
  return filters.some((filter) => filter.value === value);
}

export function ArticleListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawFilter = searchParams.get("filter");
  const filter: ArticleFilter = isArticleFilter(rawFilter) ? rawFilter : "all";
  const rawQuery = searchParams.get("q") ?? "";
  const searchQuery = rawQuery.trim();
  const query = useQuery(articlesOptions(filter, searchQuery));

  function updateSearch(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value.trim()) next.set("q", value);
    else next.delete("q");
    setSearchParams(next, { replace: true });
  }

  function selectFilter(nextFilter: ArticleFilter) {
    const next = new URLSearchParams(searchParams);
    if (nextFilter !== "all") next.set("filter", nextFilter);
    else next.delete("filter");
    setSearchParams(next, { replace: true });
  }

  return <div className={`${ui.page} ${ui.listing} ${styles.listPage}`}>
    <PageHeader
      kicker="Активна редакционна работа"
      title="Статии"
      lede="Намерете активна статия и продължете работата по нея."
    />

    <div className={ui.toolbar}>
      <div className={ui.search}>
        <label className={ui.searchLabel} htmlFor="article-search">Търсене по заглавие и текст</label>
        <input
          className={ui.searchInput}
          id="article-search"
          type="search"
          value={rawQuery}
          maxLength={200}
          onChange={(event) => updateSearch(event.target.value)}
          placeholder="Заглавие, история или текст"
        />
      </div>

      <nav className={ui.filters} aria-label="Филтър за състояние на статия">
        {filters.map((item) => <button
          className={`${ui.filter} ${filter === item.value ? ui.filterActive : ""}`}
          type="button"
          key={item.value}
          aria-pressed={filter === item.value}
          onClick={() => selectFilter(item.value)}
        >
          {item.label}
        </button>)}
      </nav>
    </div>

    {query.isPending ? <LoadingState label="Зареждане на статии…" /> : null}
    {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : null}
    {query.isSuccess && query.data.articles.length === 0 ? <EmptyState>{searchQuery ? "Няма активни статии, отговарящи на търсенето." : "Няма активни статии в този избор."}</EmptyState> : null}

    {query.isSuccess && query.data.articles.length > 0 ? <div className={ui.list} aria-busy={query.isFetching}>
      {query.data.articles.map((article) => <article className={ui.row} key={article.id}>
        <h2 className={ui.rowTitle}>
          <Link to={`/articles/${encodeURIComponent(article.id)}`}>{article.title}</Link>
        </h2>
        <p className={ui.rowSummary}>
          История:{" "}
          <Link className={styles.storyLink} to={`/stories/${encodeURIComponent(article.story.id)}`}>
            {article.story.title || "Свързана история"}
          </Link>
        </p>
        <div className={ui.statusLine}>
          <StatusMarker state={article.state} />
          {article.nextAction ? <span>Следваща стъпка: {article.nextAction.label}</span> : null}
        </div>
        <div className={ui.rowMeta}>
          <Context>Промяна: {formatDate(article.updatedAt)}</Context>
        </div>
      </article>)}
    </div> : null}
  </div>;
}
