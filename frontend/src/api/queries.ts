import { QueryClient, queryOptions } from "@tanstack/react-query";
import {
  getArchive,
  getArticle,
  getArticles,
  getFinalizedArticle,
  getStories,
  getStory,
  getToday,
  type ArticleFilter,
  type StoryFilter,
} from "./client";

export const queryKeys = {
  today: ["today"] as const,
  stories: (filter: StoryFilter, query: string) => ["stories", { filter, query }] as const,
  story: (id: string) => ["story", id] as const,
  articles: (filter: ArticleFilter, query: string) => ["articles", { filter, query }] as const,
  article: (id: string) => ["article", id] as const,
  archive: (query: string) => ["archive", { query }] as const,
  archiveArticle: (id: string) => ["archiveArticle", id] as const,
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
    queryClient.invalidateQueries({ queryKey: queryKeys.today, exact: true }),
  ]);
}

export async function invalidateStoryProjections(queryClient: QueryClient, storyId: string): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.story(storyId), exact: true }),
    queryClient.invalidateQueries({ queryKey: queryKeys.today, exact: true }),
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
    queryClient.invalidateQueries({ queryKey: queryKeys.today, exact: true }),
  ]);
}

export const todayOptions = () => queryOptions({ queryKey: queryKeys.today, queryFn: getToday });
export const storiesOptions = (filter: StoryFilter, query: string) =>
  queryOptions({ queryKey: queryKeys.stories(filter, query), queryFn: () => getStories(filter, query) });
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
