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
  const stories = useQuery(storiesOptions(filter, query));

  useEffect(() => {
    if (rawFilter !== null && !isStoryFilter(rawFilter)) {
      const next = new URLSearchParams(searchParams);
      next.delete("filter");
      setSearchParams(next, { replace: true });
    }
  }, [rawFilter, searchParams, setSearchParams]);

  function updateQuery(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value.trim()) next.set("q", value);
    else next.delete("q");
    if (filter !== "all") next.set("filter", filter);
    else next.delete("filter");
    setSearchParams(next, { replace: true });
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateQuery(searchParams.get("q") ?? "");
  }

  const items = stories.data?.stories ?? [];
  const resultMeta = stories.isFetching ? "Обновяване…" : `${items.length} ${items.length === 1 ? "история" : "истории"}`;

  return (
    <div className={`${styles.page} ${styles.listing}`}>
      <PageHeader
        kicker="Редакционен контекст"
        title="Истории"
        lede="Какво се случва в света, следено от редакцията."
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
          <button className={listStyles.searchButton} type="submit">Търсене</button>
        </div>
      </form>

      <nav className={listStyles.filterNav} aria-label="Филтри за истории">
        {storyFilters.map((option) => (
          <Link
            className={`${listStyles.filterLink} ${filter === option.value ? listStyles.filterActive : ""}`}
            to={storyHref(option.value, query)}
            aria-current={filter === option.value ? "page" : undefined}
            key={option.value}
          >
            {option.label}
          </Link>
        ))}
      </nav>

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
