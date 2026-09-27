import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, checkResearchStatus, createIdempotencyKey, makeArticleDraft, researchMoreStory, updateArticleFocus, updateArticleTitle } from "../api/client";
import { invalidateArticleProjections, queryKeys } from "../api/queries";
import type { ArticleProjection } from "../api/dto";
import { getErrorMessage } from "../shared/errorMessage";
import { ArticleContentEditor } from "./ArticleContentEditor";
import type { ArticleAutosave } from "./useArticleAutosave";
import { saveLabel } from "./articleSaveLabel";

import ui from "../shared/ui.module.css";
import { Context, EmptyState, StatusMarker } from "../shared/EditorPrimitives";
import styles from "./ArticleWorkspace.module.css";

export function PreparationWorkspace({
  article,
  autosave,
  editing,
  onEditingChange,
}: {
  article: ArticleProjection;
  /**
   * §13/§14: the ONE autosave for this Article, created by the page above.
   * Preparation does not own a second one. Two writers would be two
   * optimistic-concurrency writers racing the same content version, and the
   * second would also hold a stale body across the Preparation -> Draft
   * transition that a manual continuation causes.
   */
  autosave: ArticleAutosave;
  editing: boolean;
  onEditingChange: (value: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [title, setTitle] = useState(article.title);
  const [titleError, setTitleError] = useState("");
  const [focus, setFocus] = useState(article.editorialFocus.text);
  const [focusError, setFocusError] = useState("");
  // §D2: the backend's deterministic alternatives, served with the projection.
  // The page never derives them and never invents one.
  const focusAlternatives = article.preparation?.focusAlternatives ?? [];
  const focusFieldRef = useRef<HTMLTextAreaElement>(null);
  const [draftError, setDraftError] = useState("");
  const [draftRetryable, setDraftRetryable] = useState(false);
  const draftKey = useRef("");
  const [researchToken, setResearchToken] = useState<string | null>(null);
  const [researchError, setResearchError] = useState("");

  const acceptProjection = async (projection: ArticleProjection) => {
    queryClient.setQueryData(queryKeys.article(projection.id), projection);
    await invalidateArticleProjections(queryClient, projection.id, projection.story.id);
  };
  /**
   * Re-read the Article and its Story readiness from the server.
   *
   * Research does NOT go through `acceptProjection`: there is no fresh Article
   * payload to accept, and handing the render-time `article` to it would write
   * the pre-research projection back into the cache - a visible flash of the
   * old readiness sentence, and stale state for good if the refetch fails.
   */
  const refreshReadiness = async () => {
    await invalidateArticleProjections(queryClient, article.id, article.story.id);
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
  /**
   * §D2: one click adopts an alternative. It replaces the text and saves through
   * the SAME canonical Focus save a typed edit uses, so the adopted value is
   * immediately the active, confirmed Focus. There is no Apply, no Confirm and
   * no modal, and nothing here makes the Draft action depend on the choice.
   */
  const adoptFocus = (option: string) => {
    setFocus(option);
    setFocusError("");
    if (!focusSave.isPending) focusSave.mutate();
  };

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
  /**
   * §4: an unassessed Story is a normal preparation step with a next action, not
   * a mysterious error.
   *
   * This is a convenience adapter and nothing more: it issues the SAME
   * canonical `POST /stories/:id/research` the Story workspace issues, the
   * Story stays the sole owner of research orchestration, and there is no second
   * Article research workflow. When it finishes, the Article and its Story are
   * refetched so readiness is re-read from the server.
   */
  const research = useMutation({
    mutationFn: () => researchMoreStory(article.story.id),
    onSuccess: async (outcome) => {
      setResearchError("");
      if (outcome.status === "completed") {
        await refreshReadiness();
      } else {
        // §2: still running after the bounded wait. The token lets the editor
        // reattach to the same operation rather than start another round.
        setResearchToken(outcome.operationToken);
      }
    },
    onError: (error) => setResearchError(
      getErrorMessage(
        error,
        "Автоматичното проучване временно не е налично. Отворете историята, за да опитате отново.",
      ),
    ),
  });
  const checkResearch = useMutation({
    // The control is only reachable while a token exists; the guard keeps the
    // type honest rather than passing an empty operation id to the API.
    mutationFn: () => checkResearchStatus(researchToken ?? ""),
    onSuccess: async (outcome) => {
      setResearchError("");
      if (outcome.status === "continuing") {
        setResearchToken(outcome.operationToken);
        return;
      }
      setResearchToken(null);
      await refreshReadiness();
    },
    onError: (error) => setResearchError(getErrorMessage(error)),
  });

  const preparation = article.preparation;
  const canChangeFocus =
    article.availableActions.includes("SELECT_FOCUS") ||
    article.availableActions.includes("CHANGE_FOCUS");

  function commitTitle() {
    if (!title.trim()) {
      setTitleError("Работното заглавие не може да е празно.");
      return;
    }
    if (title.trim() !== article.title && !titleSave.isPending) titleSave.mutate();
  }
  /**
   * §5/§6/§7: the Focus saves itself. There is no confirmation step — a
   * non-empty saved Focus IS the confirmed Focus, and clearing the field
   * withdraws the confirmation so `Направи чернова` refuses with one clear
   * sentence. The editor types and moves on; the backend keeps the
   * confirmation marker in step with the text.
   */
  function commitFocus() {
    const next = focus.trim();
    if (next === (article.editorialFocus.text || "").trim()) return;
    if (!focusSave.isPending) focusSave.mutate();
  }

  return <div className={`${ui.page} ${ui.articles} ${styles.workspace}`}>
    {/* §7/§10: a short launchpad, not a form. Back link, what this is, the
        title, the state — then straight into the Focus. */}
    <header className={styles.deskHeader}>
      <div className={styles.deskHeaderTop}>
        <Link className={styles.backLink} to="/articles">← Статии</Link>
        <div className={styles.headingLine}>
          <Context>Статия</Context>
          <StatusMarker state="preparation" />
        </div>
      </div>
      {/* §7: the title lives in the header and nowhere else. It was previously
          printed as a heading AND edited in a «Работно заглавие» card below it,
          which showed the same sentence twice on one screen. While the editor
          is writing, the same header slot is fed by the ONE content autosave, so
          there is never a second writer for the title. */}
      <h1 className={styles.deskTitle}>
        {editing ? (
          <input
            className={styles.deskTitleInput}
            id="article-working-title"
            value={autosave.title}
            aria-label="Заглавие"
            onChange={(event) => autosave.change({ title: event.target.value })}
            onBlur={() => void autosave.flush()}
          />
        ) : (
          <input
            className={styles.deskTitleInput}
            id="article-working-title"
            value={title}
            maxLength={500}
            aria-label="Работно заглавие"
            aria-invalid={Boolean(titleError)}
            aria-describedby={titleError ? "article-working-title-error" : undefined}
            onChange={(event) => { setTitle(event.target.value); setTitleError(""); }}
            onBlur={commitTitle}
          />
        )}
      </h1>
      {/* §8/§14: the quiet, passive save state. While the editor is writing it
          reports the ONE content autosave; before that it reports the working
          title save. Neither is a Save button, and neither names a version. */}
      {editing ? (
        saveLabel(autosave.status) ? <p className={styles.saveStatus} role="status" aria-live="polite">{saveLabel(autosave.status)}</p> : null
      ) : titleSave.isPending ? <p className={styles.saveStatus} role="status">Запазва се…</p> : null}
      {titleError ? <p className={styles.fieldError} id="article-working-title-error" role="alert">{titleError}</p> : null}
      {editing && autosave.navigationWarning ? (
        <p className={styles.navigationWarning} role="alert">{autosave.navigationWarning}</p>
      ) : null}
      <p className={styles.linkedStory}>История:{" "}
        <Link to={`/stories/${encodeURIComponent(article.story.id)}`}>
          {article.story.title || "Свързана история"}
        </Link>
      </p>
    </header>
    <div className={styles.preparationGrid}>
      <div className={styles.preparationMain}>
        {editing ? <section className={styles.preparationSection} aria-labelledby="manual-continuation-heading">
          <h2 className={styles.contextLabel} id="manual-continuation-heading">Ръчно продължение</h2>
          {/* §15: manual continuation is a normal writing session, not an error
              mode. Its title is the one in the header, on the same autosave. */}
          <ArticleContentEditor autosave={autosave} />
        </section> : null}
        {canChangeFocus ? <section className={styles.preparationSection} aria-labelledby="article-focus-preparation">
          <h2 className={styles.contextLabel} id="article-focus-preparation">Редакционен фокус</h2>
          <p className={styles.preparationHint}>Какво конкретно искаме да разкажем с тази статия?</p>
          <label className={styles.visuallyHidden} htmlFor="article-editorial-focus">Редакционен фокус</label>
          <textarea
            className={styles.focusInput}
            id="article-editorial-focus"
            ref={focusFieldRef}
            value={focus}
            rows={5}
            maxLength={4000}
            aria-invalid={Boolean(focusError)}
            aria-describedby={focusError ? "article-editorial-focus-error" : undefined}
            onChange={(event) => { setFocus(event.target.value); setFocusError(""); }}
            onBlur={commitFocus}
          />
          {focusSave.isPending ? (
            <span className={styles.pending} role="status" aria-live="polite">Фокусът се запазва.</span>
          ) : null}
          {focusError ? <p className={styles.fieldError} id="article-editorial-focus-error" role="alert">{focusError}</p> : null}
          {/* §D2: quiet alternatives. Clicking one REPLACES the text and saves it
              through the same canonical Focus save an edit uses — no Apply, no
              Confirm, no modal, and no state of its own. §D3: the textarea above
              stays editable at all times, and «Напиши свой» only focuses it. */}
          {focusAlternatives.length ? (
            <div className={styles.focusAlternatives}>
              <p className={styles.contextLabel} id="article-focus-alternatives-label">Друг подход:</p>
              <ul aria-labelledby="article-focus-alternatives-label" className={styles.preparationList}>
                {focusAlternatives.map((option: string) => (
                  <li key={option}>
                    <button
                      type="button"
                      className={styles.focusAlternative}
                      // §34: a stable hook for the browser proof. The CSS-module
                      // class is hashed in a production build, so a class-based
                      // locator cannot be used outside the dev server.
                      data-focus-alternative={option}
                      onClick={() => adoptFocus(option)}
                    >
                      {option}
                    </button>
                  </li>
                ))}
                <li>
                  <button
                    type="button"
                    className={styles.focusAlternative}
                    data-focus-own="true"
                    onClick={() => { setFocusError(""); focusFieldRef.current?.focus(); }}
                  >
                    Напиши свой
                  </button>
                </li>
              </ul>
            </div>
          ) : null}
        </section> : <section className={styles.preparationSection} aria-labelledby="article-focus-readonly">
          <h2 className={styles.contextLabel} id="article-focus-readonly">Редакционен фокус</h2>
          <p className={styles.focusText}>{focus}</p>
        </section>}

        <section className={styles.preparationSection} aria-labelledby="preparation-readiness-heading">
          {/* §13: one block, one readiness sentence, one next action. The
              heading names what the editor is looking at, not the workflow. */}
          <h2 className={styles.contextLabel} id="preparation-readiness-heading">Фактическа основа</h2>
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
            {/*
              V1.2-G4.1 §B5: the gap questions stay on screen exactly as before,
              but the word that introduced them changed. They used to be headed
              «Пречи:», which is precisely the claim the product no longer makes —
              an open question no longer prevents writing, so it must not be
              labelled as the thing that stops you. The refusal case, where there
              genuinely is nothing to write from, is worded by the backend
              decision above and needs no second label here.
            */}
            {preparation.blockingGaps.length ? (
              <p className={styles.contextLabel} id="preparation-open-questions">
                Остава информация за проверка:
              </p>
            ) : null}
            <ul className={styles.preparationList}>
              {preparation.blockingGaps.map((gap) => <li key={gap.id} className={styles.blockingGap}>
                {gap.question}
              </li>)}
              {preparation.nonBlockingGaps.map((gap) => <li key={gap.id}>
                {gap.question}
              </li>)}
            </ul>
            {/* `MAKE_DRAFT` comes from the SAME backend decision as the sentence
                above, so an enabled Draft button and a blocking message can
                never both be on screen. */}
            {article.availableActions.includes("MAKE_DRAFT") ? (
              <div className={styles.preparationActions}>
                 {/* §23: ONE filled petrol primary action, and one calm pending
                     word while it runs. The internal stages are never shown.
                     §15: after a genuine retryable generation failure this same
                     control says so, beside the manual `Редактирай`. */}
                 <button
                   className={styles.primaryAction}
                   type="button"
                   disabled={draft.isPending || (draftError !== "" && !draftRetryable)}
                   onClick={() => draft.mutate()}
                 >
                   {draft.isPending
                     ? "Подготвя се чернова…"
                     : draftError && draftRetryable
                       ? "Опитай отново"
                       : "Направи чернова"}
                 </button>
                 {draft.isPending ? <span role="status" aria-live="polite">Черновата се създава.</span> : null}
                 {draftError ? <span className={styles.fieldError} role="alert">
                   {draftError}
                   {draftRetryable ? " Опитайте отново." : ""}
                 </span> : null}
               </div>
             ) : null}
            {/* V1.1-C: `Редактирай` is a RECOVERY path, not an alternative to
                `Направи чернова`. The backend offers it only after a genuine
                generation failure, and it renders AFTER the Draft action, which
                stays primary: a provider outage is worth a retry before the
                editor writes the story by hand. The `draftEligible` conjunct
                that used to gate this button is gone, so the button can no
                longer contradict the backend decision. */}
            {article.availableActions.includes("EDIT") ? (
              <div className={styles.preparationActions}>
                <p className={styles.pending}>
                  Автоматичното създаване не успя. Можете да опитате отново или да напишете текста сами.
                </p>
                <button className={ui.retry} type="button" onClick={() => onEditingChange(true)}>Редактирай</button>
              </div>
            ) : null}
            {/* §4/§13: when the backend says research is the remedy — including
                the unassessed case with no gap to show — the next action runs the
                canonical Story research command from here. The Story still owns
                the orchestration; this is only the way to reach it, and the
                Article + Story are refetched when it finishes. */}
            {article.availableActions.includes("RESEARCH_MORE") ? (
              <div className={styles.preparationActions}>
                <button
                  className={ui.retry}
                  type="button"
                  disabled={research.isPending || checkResearch.isPending}
                  onClick={() => (researchToken ? checkResearch.mutate() : research.mutate())}
                  data-article-research="story"
                >
                  {research.isPending || checkResearch.isPending
                    ? "Проучва се…"
                    : researchToken
                      ? "Провери статуса"
                      : "Проучи историята"}
                </button>
                {researchToken ? (
                  <span className={styles.pending} role="status" aria-live="polite">
                    Проучването продължава.
                  </span>
                ) : null}
                {researchError ? (
                  <span className={styles.fieldError} role="alert">{researchError}</span>
                ) : null}
                <Link to={`/stories/${encodeURIComponent(article.story.id)}`}>
                  Отвори историята
                </Link>
              </div>
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
    {/* V1.1-C: this notice described an Article with no Draft, so it must not
        contradict an open body editor — the editor IS the current state. It was
        rendered unconditionally, which is how "Текстът на статията още не е
        създаден." appeared directly under a textarea the editor was typing into. */}
    {!editing ? <p className={styles.noDraftNotice}>Текстът на статията още не е създаден.</p> : null}
  </div>;
}
