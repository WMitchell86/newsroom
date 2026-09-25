import { useLayoutEffect, useRef, type RefObject } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createIdempotencyKey,
  followStory,
  ignoreStory,
  researchMoreStory,
  reviewStory,
  startArticle,
  unfollowStory,
} from "../api/client";
import type { ArticleReference, MissingInformationItem, StoryDetail } from "../api/dto";
import { getErrorMessage } from "../shared/errorMessage";
import { formatDate } from "../shared/editorLabels";
import {
  invalidateArticleProjections,
  invalidateStoryProjections,
  storyOptions,
} from "../api/queries";
import {
  Disclosure,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Section,
} from "../shared/EditorPrimitives";
import styles from "./StoryWorkspace.module.css";

function articleHref(article: ArticleReference): string {
  // A finalized Article has left the active workflow: its traceability link
  // points at the read-only Archive view, never at a dead workspace.
  if (article.finalizedAt) return `/archive/${encodeURIComponent(article.id)}`;
  return `/articles/${encodeURIComponent(article.id)}`;
}

function safeExternalUrl(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

const missingKindLabels: Record<MissingInformationItem["kind"], string> = {
  missing_fact: "Липсва факт",
  conflict: "Противоречие",
  unresolved: "Неизяснен въпрос",
};

function Developments({ story }: { story: StoryDetail }) {
  const developments = story.newDevelopments.filter((item) => item.unreviewed);
  const publicationById = new Map(story.publications.map((item) => [item.id, item]));

  return (
    <Section title="Ново развитие" meta={developments.length ? String(developments.length) : "0"}>
      {developments.length ? (
        <ol className={styles.developmentList}>
          {developments.map((development) => {
            const publication = publicationById.get(development.publicationId);
            return (
              <li className={styles.development} key={development.id}>
                <h3 className={styles.itemTitle}>{development.title}</h3>
                <p className={styles.itemSummary}>{development.summary}</p>
                <p className={styles.meta}>
                  <span>Промяна: {formatDate(development.changedAt)}</span>
                  {publication ? <span>Публикация: {publication.source.name}</span> : null}
                </p>
              </li>
            );
          })}
        </ol>
      ) : <EmptyState>Няма непрегледани нови развития.</EmptyState>}
    </Section>
  );
}

function FactsAndSources({ story }: { story: StoryDetail }) {
  if (!story.factsAndSources) return null;

  return (
    <Section title="Факти и източници" meta={String(story.factsAndSources.length)}>
      {story.factsAndSources.length ? (
        <ul className={styles.factList}>
          {story.factsAndSources.map((fact) => {
            const sourceUrl = safeExternalUrl(fact.source.url);
            return (
              <li className={styles.fact} key={fact.id}>
                <p className={styles.factText}>{fact.text}</p>
                <span className={styles.sourceName}>
                  {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer">{fact.source.name}</a> : fact.source.name}
                </span>
                <p className={styles.meta}>
                  {fact.source.domain ? <span>{fact.source.domain}</span> : null}
                  {fact.locator ? <span>{fact.locator}</span> : null}
                  {fact.scope === "background" ? <span>Контекст</span> : null}
                </p>
              </li>
            );
          })}
        </ul>
      ) : <EmptyState>Няма налични факти и източници.</EmptyState>}
    </Section>
  );
}

function MissingInformationSection({ story, research }: {
  story: StoryDetail;
  research: { isPending: boolean; error: unknown; mutate: () => void };
}) {
  const missing = story.missingInformation;
  if (!missing) return null;

  return (
    <Section title="Какво липсва" meta={String(missing.items.length)}>
      {missing.items.length ? (
        <>
          <ul className={styles.gapList}>
            {missing.items.map((item) => (
              <li className={`${styles.gap} ${item.blocking ? styles.gapBlocking : ""}`} key={item.id}>
                <span className={styles.gapKind}>
                  {missingKindLabels[item.kind]}{item.blocking ? " · пречи" : ""}
                </span>
                <p className={styles.gapQuestion}>{item.question}</p>
                {item.reason ? <p className={styles.gapReason}>{item.reason}</p> : null}
              </li>
            ))}
          </ul>
          {story.availableActions.includes("RESEARCH_MORE") ? (
            <div className={styles.researchControl}>
              <button
                className={`${styles.action} ${styles.tertiaryAction}`}
                type="button"
                disabled={research.isPending}
                onClick={research.mutate}
                data-research-trigger="missing-information"
              >
                {research.isPending ? "Проучва се…" : "Проучи още"}
              </button>
              {research.isPending ? <span role="status" aria-live="polite">Проучването е в ход.</span> : null}
              {research.error ? <span role="alert" className={styles.actionError}>{getErrorMessage(research.error, "Проучването не можа да се изпълни. Опитайте отново.")}</span> : null}
            </div>
          ) : null}
        </>
      ) : <EmptyState>Няма отбелязани липсващи информации.</EmptyState>}
    </Section>
  );
}

function RelatedArticles({ story }: { story: StoryDetail }) {
  return (
    <Section title="Статии по тази история" meta={String(story.relatedArticles.length)}>
      {story.relatedArticles.length ? (
        <ul className={styles.referenceList}>
          {story.relatedArticles.map((article) => (
            <li className={styles.reference} key={article.id}>
              <h3 className={styles.itemTitle}>
                <Link to={articleHref(article)}>{article.title ?? "Свързана статия"}</Link>
              </h3>
              {article.updatedAt ? <p className={styles.meta}>Обновена: {formatDate(article.updatedAt)}</p> : null}
            </li>
          ))}
        </ul>
      ) : <EmptyState>Няма статии по тази история.</EmptyState>}
    </Section>
  );
}

function Publications({ story }: { story: StoryDetail }) {
  return (
    <Section title="Публикации">
      <Disclosure label={`Публикации (${story.publications.length})`}>
        {story.publications.length ? (
          <ul className={styles.publicationList}>
            {story.publications.map((publication) => {
              const publicationUrl = safeExternalUrl(publication.url);
              return (
                <li className={styles.publication} key={publication.id}>
                  <h3 className={styles.itemTitle}>
                    {publicationUrl ? <a href={publicationUrl} target="_blank" rel="noreferrer">{publication.title}</a> : publication.title}
                  </h3>
                  <p className={styles.meta}>
                    <span>{publication.source.name}</span>
                    {publication.source.domain ? <span>{publication.source.domain}</span> : null}
                    <span>Публикувана: {formatDate(publication.publishedAt)}</span>
                    <span>Открита: {formatDate(publication.discoveredAt)}</span>
                  </p>
                  <p className={styles.publicationSummary}>{publication.summary}</p>
                </li>
              );
            })}
          </ul>
        ) : <EmptyState>Няма публикации.</EmptyState>}
      </Disclosure>
    </Section>
  );
}

function Chronology({ story }: { story: StoryDetail }) {
  return (
    <Section title="Хронология">
      <Disclosure label={`Хронология (${story.chronology.length})`}>
        {story.chronology.length ? (
          <ol className={styles.chronologyList}>
            {story.chronology.map((event) => (
              <li className={styles.event} key={`${event.publicationId}-${event.at}-${event.title}`}>
                <p className={styles.eventKind}>{event.kind === "NEW_DEVELOPMENT" ? "Ново развитие" : "Събитие"}</p>
                <h3 className={styles.itemTitle}>{event.title}</h3>
                <p className={styles.meta}>{formatDate(event.at)}</p>
              </li>
            ))}
          </ol>
        ) : <EmptyState>Няма хронологични събития.</EmptyState>}
      </Disclosure>
    </Section>
  );
}

type StoryCommand = "REVIEW" | "FOLLOW" | "UNFOLLOW" | "IGNORE" | "START_ARTICLE";

function StoryActions({ story, headingRef }: { story: StoryDetail; headingRef: RefObject<HTMLHeadingElement | null> }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const observedDevelopmentIds = useRef<string[]>([]);
  const startArticleKey = useRef("");
  const available = (action: StoryCommand) => story.availableActions.includes(action);
  const refreshProjections = async () => {
    await invalidateStoryProjections(queryClient, story.id);
    headingRef.current?.focus();
  };
  const observed = () => [...observedDevelopmentIds.current];
  const review = useMutation({
    mutationFn: (observedIds: string[]) => reviewStory(story.id, observedIds),
    onSuccess: refreshProjections,
  });
  const follow = useMutation({
    mutationFn: () => followStory(story.id),
    onSuccess: refreshProjections,
  });
  const unfollow = useMutation({
    mutationFn: () => unfollowStory(story.id),
    onSuccess: refreshProjections,
  });
  const ignore = useMutation({
    mutationFn: () => ignoreStory(story.id),
    onSuccess: refreshProjections,
  });
  const start = useMutation({
    mutationFn: () => {
      if (!startArticleKey.current) startArticleKey.current = createIdempotencyKey();
      return startArticle(story.id, startArticleKey.current);
    },
    onSuccess: async (article) => {
      await invalidateArticleProjections(queryClient, article.id, story.id);
      navigate(`/articles/${encodeURIComponent(article.id)}`);
    },
  });
  const commandPending = review.isPending || follow.isPending || unfollow.isPending || ignore.isPending || start.isPending;

  useLayoutEffect(() => {
    observedDevelopmentIds.current = story.newDevelopments
      .filter((development) => development.unreviewed)
      .map((development) => development.id);
  }, [story.newDevelopments]);

  return (
    <>
      <div className={styles.actionCluster} aria-label="Действия за историята" aria-busy={commandPending}>
      {available("REVIEW") ? (
        <span className={styles.actionControl}>
          <button
            className={`${styles.action} ${styles.primaryAction}`}
            type="button"
            disabled={commandPending}
            onClick={() => review.mutate(observed())}
          >
            {review.isPending ? "Преглежда се…" : "Прегледай"}
          </button>
        </span>
      ) : null}
      {available("FOLLOW") ? (
        <span className={styles.actionControl}>
          <button
            className={`${styles.action} ${styles.secondaryAction}`}
            type="button"
            disabled={commandPending}
            onClick={() => follow.mutate()}
          >
            {follow.isPending ? "Следи се…" : "Следи"}
          </button>
        </span>
      ) : null}
      {available("UNFOLLOW") ? (
        <span className={styles.actionControl}>
          <button
            className={`${styles.action} ${styles.secondaryAction}`}
            type="button"
            disabled={commandPending}
            onClick={() => unfollow.mutate()}
          >
            {unfollow.isPending ? "Следването се прекратява…" : "Спри следването"}
          </button>
        </span>
      ) : null}
      {available("IGNORE") ? (
        <span className={styles.actionControl}>
          <button
            className={`${styles.action} ${styles.tertiaryAction}`}
            type="button"
            disabled={commandPending}
            onClick={() => ignore.mutate()}
          >
            {ignore.isPending ? "Игнорира се…" : "Игнорирай"}
          </button>
        </span>
      ) : null}
      {available("START_ARTICLE") ? (
        <span className={styles.actionControl}>
          <button
            className={`${styles.action} ${styles.secondaryAction}`}
            type="button"
            disabled={commandPending}
            onClick={() => start.mutate()}
          >
            {start.isPending ? "Започва се…" : "Започни статия"}
          </button>
        </span>
      ) : null}
      {start.isPending ? <span role="status" aria-live="polite">Статията се създава.</span> : null}
      {[review.error, follow.error, unfollow.error, ignore.error, start.error].map((error, index) => error ? (
        <span className={styles.actionError} role="alert" key={index}>
          {getErrorMessage(error, "Действието не можа да се изпълни. Опитайте отново.")}
        </span>
      ) : null)}
      </div>
    </>
  );
}

export function StoryWorkspace() {
  const { storyId = "" } = useParams();
  const story = useQuery({ ...storyOptions(storyId), enabled: Boolean(storyId) });
  const queryClient = useQueryClient();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const research = useMutation({
    mutationFn: () => researchMoreStory(storyId),
    onSuccess: async () => {
      await invalidateStoryProjections(queryClient, storyId);
      headingRef.current?.focus();
    },
  });

  if (!storyId) return <EmptyState>Историята не е намерена.</EmptyState>;
  if (story.isPending) return <LoadingState label="Зареждане на историята…" />;
  if (story.isError) return <ErrorState error={story.error} onRetry={() => void story.refetch()} />;

  const value = story.data;

  return (
    <div className={styles.page}>
      <PageHeader kicker="История" title={value.title} lede={value.summary} headingRef={headingRef} />
      <p className={styles.statusLine}>
        <span>Прегледана: {value.reviewed ? "да" : "не"}</span>
        <span>Следена: {value.followed ? "да" : "не"}</span>
        {value.ignored ? <span>Игнорирана</span> : null}
      </p>
      {value.ignored ? (
        <p className={styles.ignoredNotice} role="note">
          Тази история е извън фокуса на „Днес“. Прегледът ѝ връща към обичайното редакционно състояние.
        </p>
      ) : null}
      <StoryActions story={value} headingRef={headingRef} />

      <Section title="Какво се случи">
        <p className={styles.prose}>{value.whatHappened}</p>
      </Section>

      <Developments story={value} />
      <FactsAndSources story={value} />
      <MissingInformationSection story={value} research={research} />
      <RelatedArticles story={value} />
      <Publications story={value} />
      <Chronology story={value} />
    </div>
  );
}
