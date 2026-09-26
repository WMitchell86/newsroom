import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { createIdempotencyKey, ignoreStory, quickDraftStory, refreshNewsroom } from "../api/client";
import type { GroupingHealth, TodayAttention, TodayProjection } from "../api/dto";
import { queryKeys, todayOptions } from "../api/queries";
import { getErrorMessage } from "../shared/errorMessage";
import { safeInternalTarget } from "../shared/safeNavigation";
import {
  formatDate,
  formatLastRefresh,
  newPublicationsLabel,
} from "../shared/editorLabels";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Section,
} from "../shared/EditorPrimitives";
import styles from "./TodayPage.module.css";

/**
 * D1: the newsroom's own refresh context, above the attention lists.
 *
 * A never-run install says so in words. A run with failed sources is surfaced
 * as a count, because the sanitized `problems` list below is the actionable
 * form and a raw exception message has no place on the editor's first screen.
 */
function LastRefreshLine({ projection }: { projection: TodayProjection }) {
  const { lastRefresh } = projection;
  if (!lastRefresh) {
    return <p className={styles.refreshMeta}>Все още няма извършено обновяване.</p>;
  }
  const moment = formatLastRefresh(lastRefresh);
  return <p className={styles.refreshMeta}>
    {moment ? <>Последно обновяване: {moment}</> : "Последно обновяване: —"}
    {" · "}
    {newPublicationsLabel(lastRefresh.newPublications)}
    {lastRefresh.failedSources > 0 ? (
      <>
        {" · "}
        <span className={styles.refreshFailed}>
          {lastRefresh.failedSources === 1
            ? "1 проблем с източник"
            : `${lastRefresh.failedSources} проблема с източници`}
        </span>
      </>
    ) : " · 0 проблема с източници"}
  </p>;
}

/**
 * V1.1-F2A: Story grouping was conservative for part of the last run.
 *
 * The editor needs to know that some publications may appear as separate
 * Stories, because that is a real editorial consequence — not a technical
 * footnote. The wording is deliberately operational: no route ids, no provider
 * names, no HTTP categories, no model ids. Those belong in Settings later, not
 * on the first screen.
 *
 * Renders **nothing** when grouping was healthy, or when the run predates
 * grouping-health reporting: operational health must not consume editor
 * attention while there is nothing wrong.
 */
function GroupingHealthNotice({ health }: { health: GroupingHealth | null }) {
  if (!health || health.status === "healthy") {
    return null;
  }
  const degraded = health.semanticDegraded;
  const count =
    degraded === 1 ? "1 публикация" : `${degraded} публикации`;
  const message =
    health.status === "budget_exhausted"
      ? `Лимитът за групиране е изчерпан. Част от публикациите може да се показват като отделни истории (${count}).`
      : `Групирането на истории е ограничено. Част от публикациите може да се показват отделно (${count}).`;
  return (
    <p className={styles.groupingNotice} role="status">
      {message}
    </p>
  );
}

/**
 * D1: the cap is disclosed, never silent.
 *
 * Today is bounded on purpose, so the number it withheld is stated and linked
 * to the complete collection. A bounded first screen that hid its own backlog
 * would be indistinguishable from a broken one.
 */
function StoryCapNotice({ projection }: { projection: TodayProjection }) {
  const { storyAttentionTotal, storyAttentionShown } = projection;
  if (storyAttentionTotal <= storyAttentionShown) return null;
  return <p className={styles.capNotice}>
    Показани са {storyAttentionShown} от {storyAttentionTotal} текущи истории ·{" "}
    <Link to="/stories">Виж всички в Истории</Link>
  </p>;
}

function objectHref(item: TodayAttention): string {
  const base = item.objectType === "story" ? "/stories" : "/articles";
  return `${base}/${encodeURIComponent(item.objectId)}`;
}

function developmentCount(count: number): string {
  return count === 1 ? "1 ново развитие" : `${count} нови развития`;
}

function attentionReason(item: Extract<TodayAttention, { objectType: "article" }>): string {
  const labels = {
    PREPARATION: "Подготовка",
    DRAFT: "Чернова",
    READY: "Готова",
  } as const;
  return labels[item.reason];
}

/**
 * D2 §20/§23: the one status the editor sees while a Quick Draft runs.
 *
 * The backend performs several real steps — research, source opening, readiness,
 * generation — and none of them is the editor's business. It asked for one
 * thing, so it is told one thing. No stage vocabulary reaches this component.
 */
const PENDING_LABEL = "Подготвя се чернова…";

/**
 * D2 §24/§25: the two quiet controls beside the primary one.
 *
 * `Игнорирай` is the ordinary canonical Ignore command — reversible through the
 * Story surface, so it gets no confirmation dialog. `Прегледай` is a plain link
 * to the Story workspace, exactly as it was before this slice: the title link
 * beside it has always been the way to open the Story, and the row control was
 * never a review command. Neither is redefined to fit the triage layout.
 */
function StoryAttentionRow({
  item,
  queryClient,
}: {
  item: Extract<TodayAttention, { objectType: "story" }>;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const navigate = useNavigate();
  const [blocker, setBlocker] = useState<string | null>(null);
  // One key per click, reused for every retry of that click, so a double click
  // or a re-render cannot start a second orchestration (§12, §44).
  const keyRef = useRef<string | null>(null);

  const ignore = useMutation({
    mutationFn: () => ignoreStory(item.objectId),
    onSuccess: async () => {
      // Canonical refetch, never an optimistic removal: if the command failed the
      // row must still be there, and if it succeeded the server decides (§24).
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.today, exact: true }),
        queryClient.invalidateQueries({ queryKey: ["stories"] }),
      ]);
    },
    onError: (error) => {
      setBlocker(getErrorMessage(error, "Story не може да бъде игнорирана."));
    },
  });

  const quick = useMutation({
    mutationFn: () => {
      keyRef.current ??= createIdempotencyKey();
      return quickDraftStory(item.objectId, keyRef.current);
    },
    onSuccess: async (result) => {
      // §21/§22: a new Draft and an existing Draft both take the editor straight
      // to the Article. Nothing intermediate is shown or visited.
      if (result.articleId && result.status !== "needs_attention") {
        await queryClient.invalidateQueries({ queryKey: queryKeys.today, exact: true });
        navigate(`/articles/${encodeURIComponent(result.articleId)}`);
        return;
      }
      // §23: stay on Today and say what actually stopped it. One concise line,
      // and `Прегледай` stays right there next to it.
      setBlocker(result.message || "Черновата не можа да бъде подготвена.");
      await queryClient.invalidateQueries({ queryKey: queryKeys.today, exact: true });
    },
    onError: (error) => {
      setBlocker(getErrorMessage(error, "Черновата не можа да бъде подготвена."));
    },
  });

  // §4/§43: the backend is the authority. A row that carries no triage state
  // at all (an older cached projection, a Story the server has not re-projected
  // yet) still renders, and simply offers no `Чернова` — the editor is never
  // shown a button the backend did not grant.
  const actions = item.availableActions ?? [];
  const quickDraft = item.quickDraft;
  const canQuick = actions.includes("QUICK_DRAFT") && quickDraft?.available === true;
  const busy = quick.isPending;
  return (
    <li className={styles.attentionRow}>
      <div>
        <p className={styles.attentionKind}>
          {item.reason === "NEW_STORY"
            ? "Нова история"
            : developmentCount(item.delta.unreviewedDevelopmentCount)}
        </p>
        <h3 className={styles.itemTitle}>
          <Link to={objectHref(item)}>{item.title}</Link>
        </h3>
        <p className={styles.summary}>{item.summary}</p>
        <p className={styles.meta}>
          <span>Последна промяна: {formatDate(item.timestamp)}</span>
          {item.reason === "UNREVIEWED_DEVELOPMENT" ? (
            <span>Защо е тук: непрегледано ново развитие</span>
          ) : (
            <span>Защо е тук: непрегледана нова история</span>
          )}
        </p>
        {blocker ? (
          <p className={styles.blocker} role="alert">
            {blocker}
          </p>
        ) : null}
      </div>
      <div className={styles.triageActions}>
        {actions.includes("IGNORE") ? (
          <button
            className={styles.quiet}
            type="button"
            disabled={ignore.isPending || busy}
            onClick={() => {
              setBlocker(null);
              ignore.mutate();
            }}
            data-ignore-story={item.objectId}
          >
            Игнорирай
          </button>
        ) : null}
        <Link className={styles.secondary} to={objectHref(item)} data-review-story={item.objectId}>
          Прегледай
        </Link>
        {canQuick ? (
          <button
            className={styles.action}
            type="button"
            disabled={busy}
            onClick={() => {
              setBlocker(null);
              quick.mutate();
            }}
            data-quick-draft={item.objectId}
          >
            {busy ? PENDING_LABEL : quickDraft.label}
          </button>
        ) : null}
      </div>
    </li>
  );
}

/**
 * Article attention is unchanged by D2: it already points at the Article's own
 * next action, and the triage row belongs to Stories only.
 */
function ArticleAttentionRow({ item }: { item: Extract<TodayAttention, { objectType: "article" }> }) {
  return (
    <li className={styles.attentionRow}>
      <div>
        <p className={styles.attentionKind}>{attentionReason(item)}</p>
        <h3 className={styles.itemTitle}>
          <Link to={objectHref(item)}>{item.title}</Link>
        </h3>
        <p className={styles.summary}>{item.summary}</p>
        <p className={styles.meta}>
          <span>Последна промяна: {formatDate(item.timestamp)}</span>
        </p>
      </div>
      <Link className={styles.action} to={objectHref(item)}>
        {item.nextAction.label}
      </Link>
    </li>
  );
}

function AttentionRow({
  item,
  queryClient,
}: {
  item: TodayAttention;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  if (item.objectType === "story") {
    return <StoryAttentionRow item={item} queryClient={queryClient} />;
  }
  return <ArticleAttentionRow item={item} />;
}

/**
 * D1: an empty group is not rendered at all.
 *
 * A heading with a `0` and an "empty" line under it is chrome, not
 * information: on a quiet day it made Today look like a broken page. The
 * section appears only when it has something to decide.
 */
function AttentionSection({
  title,
  items,
  queryClient,
}: {
  title: string;
  items: TodayAttention[];
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  if (!items.length) return null;
  return (
    <Section title={title} meta={String(items.length)}>
      <ul className={styles.list}>
        {items.map((item) => (
          <AttentionRow item={item} queryClient={queryClient} key={`${item.objectType}-${item.objectId}`} />
        ))}
      </ul>
    </Section>
  );
}

function RefreshControl() {
  const queryClient = useQueryClient();
  const refresh = useMutation({
    mutationFn: () => refreshNewsroom(),
    onSuccess: async () => {
      // Canonical refetch: Today is the authority, and a refresh can change
      // both today's attention and every Story list projection. Nothing else is
      // flushed — the refresh never touches Article attention.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.today, exact: true }),
        queryClient.invalidateQueries({ queryKey: ["stories"] }),
      ]);
    },
  });

  return (
    <div className={styles.refreshControl}>
      <button
        className={styles.refresh}
        type="button"
        disabled={refresh.isPending}
        onClick={() => refresh.mutate()}
        data-refresh-trigger="newsroom"
      >
        {refresh.isPending ? "Обновява се…" : "Обнови"}
      </button>
      {refresh.isPending ? (
        <span className={styles.refreshStatus} role="status" aria-live="polite">
          Обновява се.
        </span>
      ) : null}
      {refresh.error ? (
        <span className={styles.refreshError} role="alert">
          {getErrorMessage(refresh.error, "Новините не можаха да се обновят. Опитайте отново.")}
        </span>
      ) : null}
    </div>
  );
}

export function TodayPage() {
  const today = useQuery(todayOptions());
  const queryClient = useQueryClient();

  if (today.isPending) return <LoadingState label="Зареждане на днешните задачи…" />;
  if (today.isError) return <ErrorState error={today.error} onRetry={() => void today.refetch()} />;

  const projection = today.data;
  const hasAttention = projection.newDevelopments.length > 0 ||
    projection.newStories.length > 0 ||
    projection.articlesRequiringAction.length > 0 ||
    projection.problems.length > 0;

  return (

    <div className={styles.page}>
      <div className={styles.headingRow}>
        <PageHeader
          kicker="Редакционно внимание"
          title="Днес"
          lede="Задачите, които изискват решение или действие сега."
        />
        <RefreshControl />
      </div>

      <LastRefreshLine projection={projection} />
      <GroupingHealthNotice health={projection.groupingHealth} />

      {hasAttention ? <div aria-live="polite">
        <AttentionSection title="Нови развития" items={projection.newDevelopments} queryClient={queryClient} />
        <AttentionSection title="Нови истории" items={projection.newStories} queryClient={queryClient} />
        <StoryCapNotice projection={projection} />
        <AttentionSection title="Статии за действие" items={projection.articlesRequiringAction} queryClient={queryClient} />
        {projection.problems.length ? (
          <Section title="Проблеми" meta={String(projection.problems.length)}>
            <ul className={styles.problemList}>
              {projection.problems.map((problem) => {
                const target = safeInternalTarget(problem.target);
                return <li className={styles.problem} key={problem.id}>
                  <h3 className={styles.itemTitle}>{problem.title}</h3>
                  <p className={styles.summary}><strong>Въздействие:</strong> {problem.consequence}</p>
                  {target ? <Link className={styles.problemLink} to={target}>{problem.label}</Link> : null}
                </li>;
              })}
            </ul>
          </Section>
        ) : null}
      </div> : <EmptyState>Няма редакционни задачи, които да изискват внимание сега.</EmptyState>}
    </div>
  );
}
