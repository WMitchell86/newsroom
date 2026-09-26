import { useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  createIdempotencyKey,
  followStory,
  ignoreStory,
  researchMoreStory,
  reviewStory,
  startArticle,
  unfollowStory,
} from "../api/client";
import { getErrorMessage } from "../shared/errorMessage";
import {
  invalidateArticleProjections,
  invalidateStoryProjections,
  storyOptions,
} from "../api/queries";
import { EmptyState, ErrorState, LoadingState } from "../shared/EditorPrimitives";
import { StoryActions } from "./story/StoryActions";
import { StoryArticleSummary } from "./story/StoryArticleSummary";
import { StoryContext } from "./story/StoryContext";
import { StoryEvidence } from "./story/StoryEvidence";
import { StoryGapList } from "./story/StoryGapList";
import { StoryGroupingCorrection } from "./story/StoryGroupingCorrection";
import { StoryHeader } from "./story/StoryHeader";
import { StoryPublications } from "./story/StoryPublications";
import { headerPrimaryAction } from "./story/storyView";
import styles from "./story/Story.module.css";

/**
 * V1.2-G2: the Story workspace.
 *
 * The page answers four questions and then gets out of the way: what happened,
 * what is confirmed, what is missing, and what can I do from here. It is the G1
 * desk at reading width — same shell, same rail, same type, same buttons — and
 * it is a *presentation* slice: the Story research semantics, the evidence
 * rules, Draft readiness, Quick Draft, grouping, ranking and every canonical
 * store are exactly as B4A and V1.1 left them.
 *
 * Two rules run through the whole page and are why it looks the way it does:
 *
 *   * **Absence renders as absence.** A section with no meaningful content is
 *     not drawn. "No facts" on an unassessed Story is not a clean evidence
 *     basis, and the page never dresses it up as one.
 *   * **The backend is the authority.** Every action comes from
 *     `availableActions`, every gap from the projection, every fact with its
 *     own source. React derives no permission, no category, no locality, no
 *     importance and no trust judgement.
 */
export function StoryWorkspace() {
  const { storyId = "" } = useParams();
  const story = useQuery({ ...storyOptions(storyId), enabled: Boolean(storyId) });
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const headingRef = useRef<HTMLHeadingElement>(null);
  // One instant for the whole render, so two relative timestamps on the page can
  // never disagree because the clock ticked between them.
  const [now] = useState(() => new Date());

  const observedDevelopmentIds = useRef<string[]>([]);
  const startArticleKey = useRef("");

  const refreshProjections = async () => {
    await invalidateStoryProjections(queryClient, storyId);
    headingRef.current?.focus();
  };

  const review = useMutation({
    mutationFn: (observedIds: string[]) => reviewStory(storyId, observedIds),
    onSuccess: refreshProjections,
  });
  const follow = useMutation({
    mutationFn: () => followStory(storyId),
    onSuccess: refreshProjections,
  });
  const unfollow = useMutation({
    mutationFn: () => unfollowStory(storyId),
    onSuccess: refreshProjections,
  });
  const ignore = useMutation({
    mutationFn: () => ignoreStory(storyId),
    onSuccess: refreshProjections,
  });
  const research = useMutation({
    mutationFn: () => researchMoreStory(storyId),
    onSuccess: refreshProjections,
  });
  const start = useMutation({
    mutationFn: () => {
      if (!startArticleKey.current) startArticleKey.current = createIdempotencyKey();
      return startArticle(storyId, startArticleKey.current);
    },
    onSuccess: async (article) => {
      await invalidateArticleProjections(queryClient, article.id, storyId);
      navigate(`/articles/${encodeURIComponent(article.id)}`);
    },
  });

  const value = story.data;
  // `Прегледай` sends exactly the A/B snapshot the editor saw, and the command
  // is what re-decides; the page keeps no unreviewed-development state of its own.
  useLayoutEffect(() => {
    observedDevelopmentIds.current = (value?.newDevelopments ?? [])
      .filter((development) => development.unreviewed)
      .map((development) => development.id);
  }, [value?.newDevelopments]);

  if (!storyId) return <EmptyState>Историята не е намерена.</EmptyState>;
  if (story.isPending) return <LoadingState label="Зареждане на историята…" />;
  if (story.isError) return <ErrorState error={story.error} onRetry={() => void story.refetch()} />;
  if (!value) return <EmptyState>Историята не е намерена.</EmptyState>;

  const researchPending = research.isPending;
  const commandError =
    [review.error, follow.error, unfollow.error, ignore.error, start.error].find(Boolean) ?? null;

  return (
    <div className={styles.page}>
      <StoryHeader story={value} now={now} headingRef={headingRef} />

      <StoryActions
        actions={value.availableActions}
        primary={headerPrimaryAction(value)}
        commands={{
          pending:
            researchPending ||
            review.isPending ||
            follow.isPending ||
            unfollow.isPending ||
            ignore.isPending ||
            start.isPending,
          reviewPending: review.isPending,
          followPending: follow.isPending,
          unfollowPending: unfollow.isPending,
          ignorePending: ignore.isPending,
          startPending: start.isPending,
          error: commandError
            ? getErrorMessage(commandError, "Действието не можа да се изпълни. Опитайте отново.")
            : null,
          onReview: () => review.mutate([...observedDevelopmentIds.current]),
          onFollow: () => follow.mutate(),
          onUnfollow: () => unfollow.mutate(),
          onIgnore: () => ignore.mutate(),
          onStartArticle: () => start.mutate(),
        }}
      />

      <StoryContext story={value} now={now} />
      <StoryEvidence story={value} />
      <StoryGapList
        story={value}
        research={{
          available: value.availableActions.includes("RESEARCH_MORE"),
          pending: researchPending,
          // §17: the backend's own sentence. The frontend never invents
          // «ненадежден източник» — a failed round says what actually failed.
          error: research.error
            ? getErrorMessage(research.error, "Проучването не можа да се изпълни. Опитайте отново.")
            : null,
          onResearch: () => research.mutate(),
        }}
      />
      <StoryArticleSummary story={value} />
      <StoryPublications story={value} />
      <StoryGroupingCorrection story={value} />
    </div>
  );
}
