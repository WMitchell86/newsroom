import { useQuery } from "@tanstack/react-query";
import { useEffect, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { StoryFilter } from "../api/client";
import { storiesOptions } from "../api/queries";
import { formatDate } from "../shared/editorLabels";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Section,
} from "../shared/EditorPrimitives";
import styles from "../shared/ui.module.css";
import listStyles from "./TodayPage.module.css";

const storyFilters: ReadonlyArray<{ value: StoryFilter; label: string }> = [
  { value: "all", label: "Всички" },
  { value: "followed", label: "Следени" },
  { value: "developments", label: "Нови развития" },
  { value: "ignored", label: "Игнорирани" },
];

function isStoryFilter(value: string | null): value is StoryFilter {
  return value === "all" || value === "followed" || value === "developments" || value === "ignored";
}

function storyHref(filter: StoryFilter, query: string): string {
  const params = new URLSearchParams();
  if (filter !== "all") params.set("filter", filter);
  if (query) params.set("q", query);
  const search = params.toString();
  return search ? `/stories?${search}` : "/stories";
}

export function StoryListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawFilter = searchParams.get("filter");
  const filter: StoryFilter = isStoryFilter(rawFilter) ? rawFilter : "all";
  const rawQuery = searchParams.get("q") ?? "";
  const query = rawQuery.trim();
  // V1.2-G4.14. The page lives in the URL for the same reason the Today desk's
  // view does (G4.11): a pager that lives in component state is reset by
  // navigating away, and Back does not mean anything.
  const page = Number(searchParams.get("page") ?? "1");
  const safePage = Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
  const stories = useQuery(storiesOptions(filter, query, safePage));

  useEffect(() => {
    if (rawFilter !== null && !isStoryFilter(rawFilter)) {
      const next = new URLSearchParams(searchParams);
      next.delete("filter");
      setSearchParams(next, { replace: true });
    }
  }, [rawFilter, searchParams, setSearchParams]);

  function updateQuery(value: string, page = 1) {
    const next = new URLSearchParams(searchParams);
    if (value.trim()) next.set("q", value);
    else next.delete("q");
    if (filter !== "all") next.set("filter", filter);
    else next.delete("filter");
    // A new filter or a new search starts at page 1. Keeping page 7 would land
    // the editor on an empty screen and read as "the search found nothing".
    if (page <= 1) next.delete("page");
    else next.set("page", String(page));
    setSearchParams(next, { replace: true });
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateQuery(searchParams.get("q") ?? "", 1);
  }

  const items = stories.data?.stories ?? [];
  const counts = stories.data?.counts;
  const total = stories.data?.total ?? items.length;
  const perPage = stories.data?.perPage ?? 30;
  const pageCount = Math.max(1, Math.ceil(total / perPage));
  const goToPage = (next: number) => {
    const params = new URLSearchParams(searchParams);
    if (next <= 1) params.delete("page");
    else params.set("page", String(next));
    setSearchParams(params, { replace: false });
  };
  const resultMeta = stories.isFetching ? "Обновяване…" : `${items.length} ${items.length === 1 ? "история" : "истории"}`;

  return (
    <div className={`${styles.page} ${styles.listing}`}>
      <PageHeader
        kicker="Редакционен контекст"
        title="Истории"
        lede="Всички истории, които редакцията е събрала. Филтрите отгоре отделят само тези, които сте маркирали — те не са разбивка на списъка."
      />

      <form className={listStyles.searchForm} role="search" onSubmit={submitSearch}>
        <label className={listStyles.searchLabel} htmlFor="story-search">Търсене в истории</label>
        <div className={listStyles.searchControls}>
          <input
            id="story-search"
            className={listStyles.searchInput}
            type="search"
            value={rawQuery}
            maxLength={200}
            placeholder="Заглавие или обобщение"
            onChange={(event) => updateQuery(event.target.value)}
          />
          {/*
            V1.2-G4.7. The button was removed, not restyled. Every keystroke
            already re-queries through onChange, so this did exactly what
            pressing Enter did, and worse, it implied the list was waiting for
            a search that was already running.
          */}
        </div>
      </form>

      <nav className={listStyles.filterNav} aria-label="Филтри за истории">
        {storyFilters.map((option) => {
          const count = counts?.[option.value];
          return (
            <Link
              className={`${listStyles.filterLink} ${filter === option.value ? listStyles.filterActive : ""}`}
              to={storyHref(option.value, query)}
              aria-current={filter === option.value ? "page" : undefined}
              key={option.value}
            >
              {option.label}
              {typeof count === "number" ? (
                <span className={listStyles.filterCount}>{count}</span>
              ) : null}
            </Link>
          );
        })}
      </nav>

      {/*
        V1.2-G4.14. Paging, not an infinite scroll: the editor needs to know a
        list has 445 things in it and be able to say "go back to page 3".
      */}
      {total > perPage ? (
        <nav className={listStyles.pager} aria-label="Страници истории">
          <button
            className={listStyles.pagerButton}
            type="button"
            disabled={safePage <= 1}
            onClick={() => goToPage(safePage - 1)}
          >
            ← Предишна
          </button>
          <span className={listStyles.pagerStatus} data-testid="pager-status">
            Страница {Math.min(safePage, pageCount)} от {pageCount} · общо {total}
          </span>
          <button
            className={listStyles.pagerButton}
            type="button"
            disabled={safePage >= pageCount}
            onClick={() => goToPage(safePage + 1)}
          >
            Следваща →
          </button>
        </nav>
      ) : null}

      {stories.isPending ? <LoadingState label="Зареждане на истории…" /> : null}
      {stories.isError ? (
        <ErrorState error={stories.error} onRetry={() => void stories.refetch()} />
      ) : null}

      {stories.isSuccess ? (
        <Section title="Списък с истории" meta={resultMeta}>
          {items.length ? (
            <ul className={styles.list}>
              {items.map((story) => (
                <li className={styles.row} key={story.id}>
                  <h2 className={styles.rowTitle}>
                    <Link to={`/stories/${encodeURIComponent(story.id)}`}>{story.title}</Link>
                  </h2>
                  <p className={styles.rowSummary}>{story.summary}</p>
                  <p className={styles.rowMeta}>
                    <span>Последна промяна: {formatDate(story.latestChangeAt)}</span>
                    {story.unreviewedDevelopmentCount > 0 ? (
                      <span>
                        {story.unreviewedDevelopmentCount === 1
                          ? "1 ново развитие"
                          : `${story.unreviewedDevelopmentCount} нови развития`}
                      </span>
                    ) : null}
                    {story.followed ? <span>Следена</span> : null}
                    {story.ignored ? <span>Игнорирана</span> : null}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState>
              {query ? "Няма истории, отговарящи на търсенето." : "Няма истории в този изглед."}
            </EmptyState>
          )}
        </Section>
      ) : null}
    </div>
  );
}
