import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { createIdempotencyKey, ignoreStory, quickDraftStory, refreshNewsroom } from "../api/client";
import type { GroupingHealth, TodayAttention, TodayProjection } from "../api/dto";
import { queryKeys, todayOptions } from "../api/queries";
import { getErrorMessage } from "../shared/errorMessage";
import { safeInternalTarget } from "../shared/safeNavigation";
import { formatDate, formatLastRefresh, newPublicationsLabel } from "../shared/editorLabels";
import { EmptyState, ErrorState, LoadingState, Section } from "../shared/EditorPrimitives";
import { TodayHeader } from "./today/TodayHeader";
import { TodayStoryRowView } from "./today/TodayStoryRow";
import { TodayToolbar } from "./today/TodayToolbar";
import {
  filterRows,
  selectTab,
  sortStoryRows,
  tabCounts,
  type TodaySort,
  type TodayTab,
} from "./today/todayView";
import styles from "./TodayPage.module.css";

/**
 * D1: the newsroom's own refresh context, above the attention list.
 *
 * A never-run install says so in words. A run with failed sources is surfaced
 * as a count, because the sanitized `problems` list below is the actionable
 * form and a raw exception message has no place on the editor's first screen.
 *
 * V1.2-G1 §7 returns this as text so the header can lay it out itself; the
 * wording and the D1 time projection are unchanged.
 */
function lastRefreshText(projection: TodayProjection): string {
  const { lastRefresh } = projection;
  if (!lastRefresh) {
    return "Все още няма извършено обновяване.";
  }
  const moment = formatLastRefresh(lastRefresh);
  const when = moment ? `Последно обновяване: ${moment}` : "Последно обновяване: —";
  const failed =
    lastRefresh.failedSources === 1
      ? "1 проблем с източник"
      : `${lastRefresh.failedSources} проблема с източници`;
  return `${when} · ${newPublicationsLabel(lastRefresh.newPublications)} · ${failed}`;
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

/** §27: which tier an Article row belongs to, in the editor's own words. */
function attentionReason(item: Extract<TodayAttention, { objectType: "article" }>): string {
  const labels = {
    PREPARATION: "Подготовка",
    DRAFT: "Чернова",
    READY: "Готова",
  } as const;
  return labels[item.reason];
}

/**
 * D2 §20/§23, now expressed through `TodayStoryActions` and `TodayBlocker`:
 * the editor asked for one thing, so the row shows one thing. No modal, no
 * wizard, and no stage vocabulary anywhere on this screen.
 *
 * `blocker` is whatever the backend said, verbatim. The frontend never composes
 * an evidence explanation and never assesses a publisher's trustworthiness.
 */

/**
 * V1.2-D2 §24/§25, now expressed through `TodayStoryActions`: the two quiet
 * controls beside the primary one.
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
  now,
}: {
  item: Extract<TodayAttention, { objectType: "story" }>;
  queryClient: ReturnType<typeof useQueryClient>;
  now: Date;
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

  return (
    <TodayStoryRowView
      row={item}
      href={objectHref(item)}
      blocker={blocker}
      busy={quick.isPending}
      ignoreDisabled={ignore.isPending}
      onIgnore={() => {
        setBlocker(null);
        ignore.mutate();
      }}
      onQuickDraft={() => {
        setBlocker(null);
        quick.mutate();
      }}
      now={now}
    />
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

/**
 * D1: an empty group is not rendered at all.
 *
 * A heading with a `0` and an "empty" line under it is chrome, not
 * information: on a quiet day it made Today look like a broken page. The
 * section appears only when it has something to decide.
 *
 * §27: this is the Article/Problems tier, and it stays strictly below the Story
 * list. Article work and operational problems are real, but they must not
 * out-shout the Stories the editor is here to triage.
 */
function SecondarySection({
  title,
  items,
}: {
  title: string;
  // The DTO types this field as the whole attention union for forward
  // compatibility, but the backend only ever emits Article rows here. The
  // narrowing is asserted at the call site rather than assumed silently.
  items: Array<Extract<TodayAttention, { objectType: "article" }>>;
}) {
  if (!items.length) return null;
  return (
    <Section title={title} meta={String(items.length)}>
      <ul className={styles.list}>
        {items.map((item) => (
          <ArticleAttentionRow item={item} key={item.objectId} />
        ))}
      </ul>
    </Section>
  );
}

/**
 * D1, restated for G1: the newsroom refresh, owned as an operation here and
 * rendered by the header.
 *
 * The button, its pending label and its error all live in `TodayHeader`, so the
 * control is not split across two components; this hook only owns the mutation
 * and the canonical refetch that follows a successful run.
 */
function useRefreshOperation() {
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
  return {
    pending: refresh.isPending,
    error: refresh.error
      ? getErrorMessage(refresh.error, "Новините не можаха да се обновят. Опитайте отново.")
      : null,
    run: () => refresh.mutate(),
  };
}

/**
 * V1.2-G1: the newsroom's first screen.
 *
 * The D1 refresh context, horizon, cap and grouping-health warning are unchanged
 * and still answered by the same backend projection. What this slice changes is
 * presentation: one header, one toolbar, one list of wire rows, and the
 * Article/Problems tier below.
 */
export function TodayPage() {
  const today = useQuery(todayOptions());
  const queryClient = useQueryClient();
  const refresh = useRefreshOperation();
  // View preferences only (§11). They live in component state, are not
  // persisted anywhere, and change nothing about the Story itself.
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<TodayTab>("all");
  const [sort, setSort] = useState<TodaySort>("newest");
  // One timestamp for the whole render, so two rows can never disagree about
  // what "преди 18 мин" means because the clock ticked between them.
  const [now] = useState(() => new Date());

  if (today.isPending) return <LoadingState label="Зареждане на днешните задачи…" />;
  if (today.isError) return <ErrorState error={today.error} onRetry={() => void today.refetch()} />;

  const projection = today.data;
  const counts = tabCounts(projection);
  // Search (§6) narrows within the chosen tab; sorting (§9) then orders what is
  // left. Both are pure functions over rows already delivered by the server.
  const rows = sortStoryRows(filterRows(selectTab(projection, tab), query), sort);
  const hasStories = rows.length > 0;

  return (
    <div className={styles.page}>
      <TodayHeader
        lastRefreshText={lastRefreshText(projection)}
        onRefresh={refresh.run}
        refreshPending={refresh.pending}
        refreshError={refresh.error}
        query={query}
        onQueryChange={setQuery}
      />

      <GroupingHealthNotice health={projection.groupingHealth} />

      <div aria-live="polite">
        <TodayToolbar
          tab={tab}
          onTabChange={setTab}
          counts={counts}
          sort={sort}
          onSortChange={setSort}
          shownCount={rows.length}
        />

        {hasStories ? (
          <ul className={styles.storyList}>
            {rows.map((row) => (
              <StoryAttentionRow
                item={row}
                queryClient={queryClient}
                now={now}
                key={row.objectId}
              />
            ))}
          </ul>
        ) : (
          <EmptyState>
            {query
              ? "Няма днешни истории, отговарящи на търсенето."
              : "Няма редакционни задачи, които да изискват внимание сега."}
          </EmptyState>
        )}

        {/* D1: the cap is disclosed, never silent — a bounded screen that hid its
            own backlog would be indistinguishable from a broken one. */}
        {hasStories ? <StoryCapNotice projection={projection} /> : null}

        {/* §27: Article work and operational problems stay below the Stories. */}
        <SecondarySection
          title="Статии за действие"
          items={projection.articlesRequiringAction.filter(
            (item): item is Extract<TodayAttention, { objectType: "article" }> =>
              item.objectType === "article",
          )}
        />
        {projection.problems.length ? (
          <Section title="Проблеми" meta={String(projection.problems.length)}>
            <ul className={styles.problemList}>
              {projection.problems.map((problem) => {
                const target = safeInternalTarget(problem.target);
                return (
                  <li className={styles.problem} key={problem.id}>
                    <h3 className={styles.itemTitle}>{problem.title}</h3>
                    <p className={styles.summary}>
                      <strong>Въздействие:</strong> {problem.consequence}
                    </p>
                    {target ? (
                      <Link className={styles.problemLink} to={target}>
                        {problem.label}
                      </Link>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </Section>
        ) : null}
      </div>
    </div>
  );
}
