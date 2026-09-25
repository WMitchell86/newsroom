import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { refreshNewsroom } from "../api/client";
import type { TodayAttention } from "../api/dto";
import { queryKeys, todayOptions } from "../api/queries";
import { getErrorMessage } from "../shared/errorMessage";
import { safeInternalTarget } from "../shared/safeNavigation";
import { formatDate } from "../shared/editorLabels";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Section,
} from "../shared/EditorPrimitives";
import styles from "./TodayPage.module.css";

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

function AttentionRow({ item }: { item: TodayAttention }) {
  return (
    <li className={styles.attentionRow}>
      <div>
        <p className={styles.attentionKind}>
          {item.objectType === "story"
            ? item.reason === "NEW_STORY"
              ? "Нова история"
              : developmentCount(item.delta.unreviewedDevelopmentCount)
            : attentionReason(item)}
        </p>
        <h3 className={styles.itemTitle}>
          <Link to={objectHref(item)}>{item.title}</Link>
        </h3>
        <p className={styles.summary}>{item.summary}</p>
        <p className={styles.meta}>
          <span>Последна промяна: {formatDate(item.timestamp)}</span>
          {item.objectType === "story" && item.reason === "UNREVIEWED_DEVELOPMENT" ? (
            <span>Защо е тук: непрегледано ново развитие</span>
          ) : null}
          {item.objectType === "story" && item.reason === "NEW_STORY" ? (
            <span>Защо е тук: непрегледана нова история</span>
          ) : null}
        </p>
      </div>
      <Link className={styles.action} to={objectHref(item)}>
        {item.objectType === "story" ? "Прегледай" : item.nextAction.label}
      </Link>
    </li>
  );
}

function AttentionSection({ title, items }: { title: string; items: TodayAttention[] }) {
  return (
    <Section title={title} meta={items.length ? String(items.length) : "0"}>
      {items.length ? (
        <ul className={styles.list}>
          {items.map((item) => <AttentionRow item={item} key={`${item.objectType}-${item.objectId}`} />)}
        </ul>
      ) : <EmptyState>Няма записи в тази група.</EmptyState>}
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

      {hasAttention ? <div aria-live="polite">
        <AttentionSection title="Нови развития" items={projection.newDevelopments} />
        <AttentionSection title="Нови истории" items={projection.newStories} />
        <AttentionSection title="Статии за действие" items={projection.articlesRequiringAction} />
        <Section title="Проблеми" meta={String(projection.problems.length)}>
          {projection.problems.length ? (
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
          ) : null}
        </Section>
      </div> : <EmptyState>Няма редакционни задачи, които да изискват внимание сега.</EmptyState>}
    </div>
  );
}
