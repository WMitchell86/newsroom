import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { archiveArticleOptions } from "../api/queries";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, Disclosure } from "../shared/EditorPrimitives";
import { formatDate } from "../shared/editorLabels";
import styles from "./SupportingPages.module.css";

export function FinalizedArticleView() {
  const { articleId = "" } = useParams();
  const article = useQuery({ ...archiveArticleOptions(articleId), enabled: Boolean(articleId) });

  if (!articleId) {
    return <ErrorState title="Финализираната статия не е намерена" error={new Error("Липсва идентификатор на статията.")} />;
  }
  if (article.isPending) return <LoadingState label="Зареждане на финализираната статия…" />;
  if (article.isError) {
    return <ErrorState title="Финализираната статия не можа да се зареди" error={article.error} onRetry={() => void article.refetch()} />;
  }

  const value = article.data;
  const currentTitle = value.content.title || value.title;
  const facts = value.factsAndSources;
  const missing = value.missingInformation;

  return <div className={`${styles.page} ${styles.finalizedPage}`}>
    <PageHeader kicker="Финализирана статия" title={currentTitle} lede="Завършено в системата · без редакционни действия" article />

    <div className={styles.finalizedMeta}>
      <p>
        История:{" "}
        <Link to={`/stories/${encodeURIComponent(value.story.id)}`}>
          {value.story.title || "Свързана история"}
        </Link>
      </p>
      <p>Финализирана на: {formatDate(value.finalizedAt)}</p>
    </div>

    <div className={styles.finalizedLayout}>
      <div>
        <section className={styles.focusPanel} aria-labelledby="finalized-focus-heading">
          <h2 className={styles.sectionLabel} id="finalized-focus-heading">Редакционен фокус</h2>
          {value.editorialFocus.text
            ? <p className={styles.focusText}>{value.editorialFocus.text}</p>
            : <EmptyState>Няма записан редакционен фокус.</EmptyState>}
        </section>

        <Section title="Текущо съдържание" meta={`Версия ${value.content.version}`}>
          {currentTitle ? <h2 className={styles.contentTitle}>{currentTitle}</h2> : null}
          {value.content.body.trim()
            ? <p className={styles.contentBody}>{value.content.body}</p>
            : <EmptyState>Няма текст на финализираната статия.</EmptyState>}
        </Section>
      </div>

      {/* The traceability the Archive was frozen with, read-only. */}
      <Disclosure label="Факти, източници и липсваща информация">
        {facts.length > 0 ? <section>
          <h2 className={styles.sectionLabel}>Факти и източници</h2>
          <ul>
            {facts.map((fact) => <li key={fact.id}>
              <p>{fact.text}</p>
              <p>
                <strong>{fact.source.name}</strong>
                {fact.source.domain ? <span> · {fact.source.domain}</span> : null}
                {fact.locator ? <span> · {fact.locator}</span> : null}
              </p>
            </li>)}
          </ul>
        </section> : null}
        {missing ? <section>
          <h2 className={styles.sectionLabel}>Какво липсваше по време на финализирането</h2>
          <p>Оценено на {formatDate(missing.assessedAt)}</p>
          {missing.items.length === 0 ? <p>Няма липсваща информация.</p> : (
            <ul>
              {missing.items.map((item) => <li key={item.id}>
                <p>{item.question}</p>
                {item.reason ? <p>{item.reason}</p> : null}
              </li>)}
            </ul>
          )}
        </section> : null}
      </Disclosure>
    </div>
  </div>;
}
