import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";
import { articleOptions, queryKeys } from "../api/queries";
import {
  Context,
  Disclosure,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Section,
  StatusMarker,
} from "../shared/EditorPrimitives";
import { formatDate } from "../shared/editorLabels";
import { safeExternalUrl } from "../shared/safeNavigation";
import { ArticleContentEditor } from "./ArticleContentEditor";
import { PreparationWorkspace } from "./PreparationWorkspace";
import ui from "../shared/ui.module.css";
import styles from "./ArticleWorkspace.module.css";
function contentHeading(state: "preparation" | "draft" | "ready") {
  if (state === "draft") return "Чернова";
  if (state === "ready") return "Финален преглед";
  return "Текущо съдържание";
}



export function ArticleWorkspace() {
  const { articleId = "" } = useParams();
  const query = useQuery({ ...articleOptions(articleId), enabled: Boolean(articleId) });
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  if (!articleId) {
    return <ErrorState title="Статията не е намерена" error={new Error("Липсва идентификатор на статия.")} />;
  }
  if (query.isPending) return <LoadingState label="Зареждане на статия…" />;
  if (query.isError) {
    return <ErrorState title="Статията не можа да се зареди" error={query.error} onRetry={() => void query.refetch()} />;
  }
  const article = query.data;

  if (article.isFinalized || article.state === null) {
    return <Navigate replace to={`/archive/${encodeURIComponent(article.id)}`} />;
  }
  if (article.state === "preparation") {
    return <PreparationWorkspace
      article={article}
      editing={editing}
      onEditingChange={setEditing}
      onProjection={(projection) => {
        queryClient.setQueryData(queryKeys.article(article.id), projection);
        setSavedVersion(projection.content.version);
      }}
    />;
  }
  const facts = article.factsAndSources;
  const missing = article.missingInformation;
  const currentTitle = article.content.title || article.title;

  return <div className={`${ui.page} ${ui.articles} ${styles.workspace}`}>
    <header className={styles.workspaceHeader}>
      <div className={styles.headingLine}>
        <Context>Статия</Context>
        <StatusMarker state={article.state} />
      </div>
      <PageHeader kicker="Активна редакционна работа" title={currentTitle} article />
      <p className={styles.linkedStory}>
        Свързана история:{" "}
        <Link to={`/stories/${encodeURIComponent(article.story.id)}`}>
          {article.story.title || "Отвори историята"}
        </Link>
      </p>
    </header>

    <div className={styles.workspaceGrid}>
      <div className={styles.editorialColumn}>
        <section className={styles.focus} aria-labelledby="article-focus">
          <h2 className={styles.contextLabel} id="article-focus">Редакционен фокус</h2>
          {article.editorialFocus.text
            ? <p className={styles.focusText}>{article.editorialFocus.text}</p>
            : <p className={styles.focusEmpty}>Още не е зададен фокус.</p>}
        </section>

        <section className={styles.content} aria-labelledby="article-content-heading">
          <div className={styles.contentHeader}>
            <h2 className={styles.contentHeading} id="article-content-heading">
              {contentHeading(article.state)}
            </h2>
            <div className={styles.contentControls}>
              <Context>Версия {article.content.version}</Context>
              {article.availableActions.includes("EDIT") ? (
                <button
                  className={ui.retry}
                  type="button"
                  onClick={() => setEditing((current) => !current)}
                >
                  {editing ? "Завърши редакцията" : "Редактирай"}
                </button>
              ) : null}
            </div>
          </div>
          {editing ? <ArticleContentEditor article={article} savedVersion={savedVersion} /> : <>
            {currentTitle ? <h3 className={styles.contentTitle}>{currentTitle}</h3> : null}
            {article.content.body.trim()
              ? <p className={styles.contentBody}>{article.content.body}</p>
              : <EmptyState>Още няма текст на статията.</EmptyState>}
          </>}
        </section>

        <Section title="Готовност" meta={article.readiness.isCurrent ? "Актуална" : "Не е актуална"}>
          <dl className={styles.readiness}>
            <div>
              <dt>Версия на проверката</dt>
              <dd>{article.readiness.readyVersion ?? "Няма"}</dd>
            </div>
            <div>
              <dt>Проверена на</dt>
              <dd>{formatDate(article.readiness.readyAt)}</dd>
            </div>
          </dl>
        </Section>

        <section className={styles.warnings} aria-labelledby="article-warnings-heading">
          <h2 className={ui.sectionTitle} id="article-warnings-heading">Предупреждения</h2>
          {article.warnings.length === 0
            ? <p className={styles.noWarnings}>Няма предупреждения.</p>
            : <ul className={styles.warningList}>
              {article.warnings.map((warning) => <li
                className={`${styles.warning} ${warning.blocking ? styles.warningBlocking : ""}`}
                key={warning.id}
              >
                <p className={styles.warningMessage}>{warning.message}</p>
                {warning.affectedText ? <p className={styles.affectedText}>{warning.affectedText}</p> : null}
              </li>)}
            </ul>}
        </section>
      </div>

      <aside className={styles.evidenceColumn} aria-label="Факти, източници и липсваща информация">
        <Disclosure label="Факти, източници и липсваща информация">
          {facts.length > 0 ? <section className={styles.evidenceSection}>
            <h2 className={styles.evidenceHeading}>Факти и източници</h2>
            <ul className={styles.factList}>
              {facts.map((fact) => <li className={styles.fact} key={fact.id}>
                <p className={styles.factText}>{fact.text}</p>
                <p className={styles.source}>
                  <strong>{fact.source.name}</strong>
                  {fact.source.domain ? <span> · {fact.source.domain}</span> : null}
                  {fact.locator ? <span> · {fact.locator}</span> : null}
                </p>
                {(() => {
                  const sourceUrl = safeExternalUrl(fact.source.url);
                  return sourceUrl ? <a className={styles.sourceLink} href={sourceUrl} target="_blank" rel="noreferrer">
                    Отвори източника
                  </a> : null;
                })()}
              </li>)}
            </ul>
          </section> : null}

          {missing ? <section className={styles.evidenceSection}>
            <h2 className={styles.evidenceHeading}>Какво липсва</h2>
            <p className={styles.evidenceMeta}>Оценено на {formatDate(missing.assessedAt)}</p>
            {missing.items.length === 0 ? <p className={styles.evidenceEmpty}>Няма липсваща информация.</p> : null}
            {missing.items.length > 0 ? <ul className={styles.missingList}>
              {missing.items.map((item) => <li className={styles.missingItem} key={item.id}>
                <p className={styles.missingQuestion}>{item.question}</p>
                {item.reason ? <p className={styles.missingReason}>{item.reason}</p> : null}
              </li>)}
            </ul> : null}
          </section> : null}
          {facts.length === 0 && !missing ? <p className={styles.evidenceEmpty}>Няма налични факти и източници.</p> : null}
        </Disclosure>
      </aside>
    </div>
  </div>;
}

