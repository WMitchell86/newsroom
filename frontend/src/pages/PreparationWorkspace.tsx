import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, createIdempotencyKey, makeArticleDraft, updateArticleFocus, updateArticleTitle } from "../api/client";
import { invalidateArticleProjections, queryKeys } from "../api/queries";
import type { ArticleProjection } from "../api/dto";
import { getErrorMessage } from "../shared/errorMessage";
import { ArticleContentEditor } from "./ArticleContentEditor";

import ui from "../shared/ui.module.css";
import { Context, EmptyState, PageHeader, StatusMarker } from "../shared/EditorPrimitives";
import styles from "./ArticleWorkspace.module.css";

export function PreparationWorkspace({
  article,
  editing,
  onEditingChange,
  onProjection,
}: {
  article: ArticleProjection;
  editing: boolean;
  onEditingChange: (value: boolean) => void;
  onProjection: (projection: ArticleProjection) => void;
}) {
  const queryClient = useQueryClient();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [title, setTitle] = useState(article.title);
  const [titleError, setTitleError] = useState("");
  const [focus, setFocus] = useState(article.editorialFocus.text);
  const [focusError, setFocusError] = useState("");
  const [draftError, setDraftError] = useState("");
  const [draftRetryable, setDraftRetryable] = useState(false);
  const draftKey = useRef("");

  const acceptProjection = async (projection: ArticleProjection) => {
    queryClient.setQueryData(queryKeys.article(projection.id), projection);
    await invalidateArticleProjections(queryClient, projection.id, projection.story.id);
  };
  const titleSave = useMutation({
    mutationFn: () => updateArticleTitle(article.id, article.content.version, title.trim()),
    onSuccess: async (projection) => {
      setTitleError("");
      await acceptProjection(projection);
    },
    onError: (error) => {
      setTitleError(
        getErrorMessage(error, "Заглавието не може да бъде запазено. Текстът е запазен тук.")
      );
      if (error instanceof ApiError && error.code === "ARTICLE_VERSION_CONFLICT") {
        void queryClient.refetchQueries({ queryKey: queryKeys.article(article.id), exact: true });
      }
    },
  });
  const focusSave = useMutation({
    mutationFn: () => updateArticleFocus(article.id, focus.trim()),
    onSuccess: async (projection) => {
      setFocusError("");
      await acceptProjection(projection);
      headingRef.current?.focus();
    },
    onError: (error) => setFocusError(
      getErrorMessage(error, "Фокусът не може да бъде запазен. Текстът е запазен тук.")
    ),
  });
  const draft = useMutation({
    mutationFn: () => {
      if (!draftKey.current) draftKey.current = createIdempotencyKey();
      return makeArticleDraft(article.id, draftKey.current);
    },
    onMutate: () => {
      setDraftError("");
      setDraftRetryable(false);
    },
    onSuccess: async (projection) => {
      await acceptProjection(projection);
      setDraftError("");
    },
    onError: (error) => {
      setDraftError(getErrorMessage(error, "Черновата не можа да бъде създадена. Опитайте отново."));
      setDraftRetryable(error instanceof ApiError ? error.retryable : false);
    },
  });
  const preparation = article.preparation;
  const canChangeFocus =
    article.availableActions.includes("SELECT_FOCUS") ||
    article.availableActions.includes("CHANGE_FOCUS");
  const confirmed = article.availableActions.includes("CHANGE_FOCUS");

  function commitTitle() {
    if (!title.trim()) {
      setTitleError("Работното заглавие не може да е празно.");
      return;
    }
    if (title.trim() !== article.title && !titleSave.isPending) titleSave.mutate();
  }
  function commitFocus(event: React.FormEvent) {
    event.preventDefault();
    if (!focus.trim()) {
      setFocusError("Изберете фокус за статията.");
      return;
    }
    if (!focusSave.isPending) focusSave.mutate();
  }

  return <div className={`${ui.page} ${ui.articles} ${styles.workspace}`}>
    <header className={styles.workspaceHeader}>
      <div className={styles.headingLine}>
        <Context>Статия</Context>
        <StatusMarker state="preparation" />
      </div>
      <PageHeader kicker="Активна редакционна работа" title={article.title} article headingRef={headingRef} />
      <p className={styles.linkedStory}>Свързана история:{" "}
        <Link to={`/stories/${encodeURIComponent(article.story.id)}`}>
          {article.story.title || "Отвори историята"}
        </Link>
      </p>
    </header>
    <div className={styles.preparationGrid}>
      <div className={styles.preparationMain}>
        {editing ? <section className={styles.preparationSection} aria-labelledby="manual-continuation-heading">
          <h2 className={styles.contextLabel} id="manual-continuation-heading">Ръчно продължение</h2>
          <ArticleContentEditor article={article} onSaved={onProjection} />
        </section> : null}
        {!editing ? <section className={styles.preparationSection} aria-labelledby="working-title-heading">
          <h2 className={styles.contextLabel} id="working-title-heading">Работно заглавие</h2>
          <label className={styles.visuallyHidden} htmlFor="article-working-title">Работно заглавие</label>
          <input
            className={styles.titleInput}
            id="article-working-title"
            value={title}
            maxLength={500}
            aria-invalid={Boolean(titleError)}
            aria-describedby={titleError ? "article-working-title-error" : undefined}
            onChange={(event) => { setTitle(event.target.value); setTitleError(""); }}
            onBlur={commitTitle}
          />
          {titleSave.isPending ? <span className={styles.pending} role="status">Заглавието се запазва.</span> : null}
          {titleError ? <p className={styles.fieldError} id="article-working-title-error" role="alert">{titleError}</p> : null}
        </section> : null}

        {canChangeFocus ? <form className={styles.preparationSection} onSubmit={commitFocus} aria-labelledby="article-focus-preparation">
          <h2 className={styles.contextLabel} id="article-focus-preparation">Редакционен фокус</h2>
          <p className={styles.preparationHint}>Какво конкретно искаме да разкажем с тази статия?</p>
          {!confirmed ? <p className={styles.confirmationNote}>Фокусът е предложение и очаква редакторско решение.</p> : null}
          <label className={styles.visuallyHidden} htmlFor="article-editorial-focus">Редакционен фокус</label>
          <textarea
            className={styles.focusInput}
            id="article-editorial-focus"
            value={focus}
            rows={5}
            maxLength={4000}
            aria-invalid={Boolean(focusError)}
            aria-describedby={focusError ? "article-editorial-focus-error" : undefined}
            onChange={(event) => { setFocus(event.target.value); setFocusError(""); }}
          />
          <div className={styles.preparationActions}>
            <button className={ui.retry} type="submit" disabled={focusSave.isPending}>
              {focusSave.isPending ? "Запазва се…" : confirmed ? "Промени фокуса" : "Избери фокус"}
            </button>
            {focusSave.isPending ? <span role="status" aria-live="polite">Фокусът се потвърждава.</span> : null}
          </div>
          {focusError ? <p className={styles.fieldError} id="article-editorial-focus-error" role="alert">{focusError}</p> : null}
        </form> : <section className={styles.preparationSection} aria-labelledby="article-focus-readonly">
          <h2 className={styles.contextLabel} id="article-focus-readonly">Редакционен фокус</h2>
          <p className={styles.focusText}>{focus}</p>
        </section>}

        <section className={styles.preparationSection} aria-labelledby="preparation-readiness-heading">
          <h2 className={styles.contextLabel} id="preparation-readiness-heading">Подготовка за чернова</h2>
          {preparation ? <>
            {/* V1.1-B: exactly ONE readiness sentence, taken verbatim from the
                backend decision. There is no second, competing explanation, so
                a green line can never appear beside a blocking one. */}
            <p
              className={preparation.draftEligible ? styles.eligible : styles.notEligible}
              data-readiness-code={preparation.draftReadiness.code}
            >
              {preparation.draftReadiness.message}
            </p>
            {preparation.blockingGaps.length ? (
              <p className={styles.pending}>
                <Link to={`/stories/${encodeURIComponent(article.story.id)}`}>
                  Отвори историята, за да проучиш още
                </Link>
              </p>
            ) : null}
            <ul className={styles.preparationList}>
              {preparation.blockingGaps.map((gap) => <li key={gap.id} className={styles.blockingGap}>
                <strong>Пречи:</strong> {gap.question}
              </li>)}
              {preparation.nonBlockingGaps.map((gap) => <li key={gap.id}>
                <strong>Липсва, но не пречи:</strong> {gap.question}
              </li>)}
            </ul>
            {article.availableActions.includes("EDIT") && preparation.draftEligible ? (
              <div className={styles.preparationActions}>
                <button className={ui.retry} type="button" onClick={() => onEditingChange(true)}>Редактирай</button>
              </div>
            ) : null}
            {/* `MAKE_DRAFT` comes from the SAME backend decision as the sentence
                above, so an enabled Draft button and a blocking message can
                never both be on screen. */}
            {article.availableActions.includes("MAKE_DRAFT") ? (
              <div className={styles.preparationActions}>
                 <button
                   className={ui.retry}
                   type="button"
                   disabled={draft.isPending || (draftError !== "" && !draftRetryable)}
                   onClick={() => draft.mutate()}
                 >
                   {draft.isPending ? "Черновата се създава…" : "Направи чернова"}
                 </button>
                 {draft.isPending ? <span role="status" aria-live="polite">Черновата се създава.</span> : null}
                 {draftError ? <span className={styles.fieldError} role="alert">
                   {draftError}
                   {draftRetryable ? " Опитайте отново." : ""}
                 </span> : null}
               </div>
             ) : null}
            {/* Research stays owned by the Story. When the backend says research
                is the remedy, the editor gets a direct path to it — even with no
                gap to show, which is the unassessed case. */}
            {article.availableActions.includes("RESEARCH_MORE") ? (
              <p className={styles.pending}>
                <Link to={`/stories/${encodeURIComponent(article.story.id)}`}>
                  Проучи още
                </Link>
              </p>
            ) : null}

          </> : <EmptyState>Няма проекция за подготовката.</EmptyState>}
        </section>
      </div>

      <aside className={styles.preparationEvidence} aria-labelledby="preparation-evidence-heading">
        <h2 className={styles.contextLabel} id="preparation-evidence-heading">Факти и източници</h2>
        {article.factsAndSources.length ? <ul className={styles.preparationList}>
          {article.factsAndSources.map((fact) => <li key={fact.id}>
            <p>{fact.text}</p>
            <span>{fact.source.name}</span>
          </li>)}
        </ul> : <p className={styles.pending}>Няма налични факти и източници.</p>}
      </aside>
    </div>
    <p className={styles.noDraftNotice}>Текстът на статията още не е създаден.</p>
  </div>;
}
