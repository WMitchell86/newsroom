import { QueryClient, queryOptions } from "@tanstack/react-query";
import {
  getArchive,
  getArticle,
  getArticles,
  getFeedbackSettings,
  getFinalizedArticle,
  getSources,
  getStories,
  getStory,
  getToday,
  type ArticleFilter,
  type StoryFilter,
} from "./client";
import type { TodayScope } from "./dto";

export const queryKeys = {
  // V1.2-G4.1 §A4: the scope is part of the key, so `region` and `all`
  // can never be served from one another's cache entry.
  today: (scope: TodayScope = "region") => ["today", scope] as const,
  stories: (filter: StoryFilter, query: string) => ["stories", { filter, query }] as const,
  story: (id: string) => ["story", id] as const,
  articles: (filter: ArticleFilter, query: string) => ["articles", { filter, query }] as const,
  article: (id: string) => ["article", id] as const,
  archive: (query: string) => ["archive", { query }] as const,
  archiveArticle: (id: string) => ["archiveArticle", id] as const,
  /** V1.2-G4: one canonical registry, one query key. */
  sources: ["sources"] as const,
  /** V1.2-G4.3 §G: the controlled learning loop, one key. */
  feedback: ["feedback"] as const,
  /** V1.2-G4.39: the paid-model switch, one key. */
  modelSettings: ["modelSettings"] as const,
};

export async function invalidateArticleProjections(
  queryClient: QueryClient,
  articleId: string,
  storyId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.article(articleId), exact: true }),
    queryClient.invalidateQueries({ queryKey: queryKeys.story(storyId), exact: true }),
    queryClient.invalidateQueries({ queryKey: ["articles"] }),
    queryClient.invalidateQueries({ queryKey: ["today"] }),
  ]);
}

export async function invalidateStoryProjections(queryClient: QueryClient, storyId: string): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.story(storyId), exact: true }),
    queryClient.invalidateQueries({ queryKey: ["today"] }),
    queryClient.invalidateQueries({ queryKey: ["stories"] }),
  ]);
}

/**
 * `Финализирай`: the Article leaves the active surfaces and enters the Archive.
 * Nothing is removed from the cache by hand - the server already succeeded, so
 * the canonical projections are simply refetched.
 */
export async function invalidateFinalizedArticle(
  queryClient: QueryClient,
  articleId: string,
  storyId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.article(articleId), exact: true }),
    queryClient.invalidateQueries({ queryKey: queryKeys.archiveArticle(articleId), exact: true }),
    queryClient.invalidateQueries({ queryKey: queryKeys.story(storyId), exact: true }),
    queryClient.invalidateQueries({ queryKey: ["articles"] }),
    queryClient.invalidateQueries({ queryKey: ["archive"] }),
    queryClient.invalidateQueries({ queryKey: ["today"] }),
  ]);
}

export const todayOptions = (scope: TodayScope = "region") =>
  queryOptions({ queryKey: queryKeys.today(scope), queryFn: () => getToday(scope) });
/** V1.2-G4.14: the page is part of the cache key, or page 2 would show page 1. */
export const storiesOptions = (filter: StoryFilter, query: string, page = 1) =>
  queryOptions({
    // The page belongs in the key. Without it, "next page" reads a cache entry
    // that already holds page 1 and shows the same rows again.
    queryKey: [...queryKeys.stories(filter, query), page],
    queryFn: () => getStories(filter, query, page),
  });
export const storyOptions = (id: string) =>
  queryOptions({ queryKey: queryKeys.story(id), queryFn: () => getStory(id) });
export const articlesOptions = (filter: ArticleFilter, query: string) =>
  queryOptions({
    queryKey: queryKeys.articles(filter, query),
    queryFn: () => getArticles(filter, query),
  });
export const articleOptions = (id: string) =>
  queryOptions({ queryKey: queryKeys.article(id), queryFn: () => getArticle(id) });
export const archiveOptions = (query: string) =>
  queryOptions({ queryKey: queryKeys.archive(query), queryFn: () => getArchive(query) });
export const archiveArticleOptions = (id: string) =>
  queryOptions({ queryKey: queryKeys.archiveArticle(id), queryFn: () => getFinalizedArticle(id) });
export const sourcesOptions = () => queryOptions({ queryKey: queryKeys.sources, queryFn: getSources });
export const feedbackOptions = () =>
  queryOptions({ queryKey: queryKeys.feedback, queryFn: getFeedbackSettings });
