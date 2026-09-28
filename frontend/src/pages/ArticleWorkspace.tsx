import { useCallback, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import {
  articleOptions,
  invalidateArticleProjections,
  invalidateFinalizedArticle,
  queryKeys,
} from "../api/queries";
import { createIdempotencyKey, finalizeArticle, markArticleReady, reopenArticle } from "../api/client";
import {
  Context,
  ErrorState,
  LoadingState,
  StatusMarker,
} from "../shared/EditorPrimitives";
import { getErrorMessage } from "../shared/errorMessage";
import { safeExternalUrl } from "../shared/safeNavigation";
import { ArticleContentEditor } from "./ArticleContentEditor";
import { ArticleDeskTitle, DraftFocusBlock } from "./ArticleDeskParts";
import { PreparationWorkspace } from "./PreparationWorkspace";
import { useArticleAutosave } from "./useArticleAutosave";
import ui from "../shared/ui.module.css";
import styles from "./ArticleWorkspace.module.css";
import type { ArticleDetail, Warning } from "../api/dto";

function contentHeading(state: "draft" | "ready") {
  if (state === "draft") return "Чернова";
  // The state itself is announced once, by the status marker. The section
  // heading names what the editor is looking at, not the state a second time.
  return "Финален преглед";
}

/** The frozen three-level visual hierarchy: quiet note, editorial note, strong stop. */
function warningClass(warning: Warning) {
  const base = styles.warning;
  if (warning.blocking || warning.severity === "blocking") return `${base} ${styles.warningBlocking}`;
  if (warning.severity === "info") return `${base} ${styles.warningInfo}`;
  return `${base} ${styles.warningReview}`;
}



/**
 * V1.2-G3: the query shell.
 *
 * Everything that must run before the canonical Article exists lives here, and
 * everything that owns an autosave lives BELOW it. Splitting the component at
 * the loading boundary is what lets the writing desk call its hooks
 * unconditionally instead of after an early return.
 */
export function ArticleWorkspace() {
  const { articleId = "" } = useParams();
  const query = useQuery({ ...articleOptions(articleId), enabled: Boolean(articleId) });

  if (!articleId) {
    return <ErrorState title="Статията не е намерена" error={new Error("Липсва идентификатор на статия.")} />;
  }
  if (query.isPending) return <LoadingState label="Зареждане на статия…" />;
  if (query.isError) {
    return <ErrorState title="Статията не можа да се зареди" error={query.error} onRetry={() => void query.refetch()} />;
  }
  return <ArticleDesk article={query.data} />;
}

/** The writing desk. Hooks run unconditionally here; the Article always exists. */
function ArticleDesk({ article }: { article: ArticleDetail }) {
  const articleId = article.id;
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
  const [readyError, setReadyError] = useState("");
  const [transitionError, setTransitionError] = useState("");
  // §19: the support rail is open by default while there is something in it, and
  // collapsing it gives the writing column the full width. No draggable pane.
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const flushRef = useRef<(() => Promise<boolean>) | null>(null);
  const registerFlush = useCallback((flush: (() => Promise<boolean>) | null) => {
    flushRef.current = flush;
  }, []);

  // «Отбележи като готова». A pending autosave is confirmed first, so the
  // expected version is always the version the server actually holds. The
  // server revalidates anyway: this decides only *which* version to ask about.
  const ready = useMutation({
    mutationFn: async () => {
      const flushed = flushRef.current ? await flushRef.current() : true;
      if (!flushed) throw new Error("unconfirmed");
      const confirmed = queryClient.getQueryData<ArticleDetail>(queryKeys.article(articleId));
      return markArticleReady(articleId, confirmed?.content.version ?? 0);
    },
    onMutate: () => setReadyError(""),
    onSuccess: async (projection) => {
      queryClient.setQueryData(queryKeys.article(projection.id), projection);
      await invalidateArticleProjections(queryClient, projection.id, projection.story.id);
      setSavedVersion(projection.content.version);
    },
    onError: async (error) => {
      setReadyError(
        getErrorMessage(error, "Статията не можа да се отбележи като готова. Опитайте отново."),
      );
      // The canonical Article is the authority after a refusal: a blocking
      // issue, a newer version or a failed check must be shown, not guessed.
      await queryClient.invalidateQueries({ queryKey: queryKeys.article(articleId), exact: true });
    },
  });

  // «Редактирай» from `Готова`. The editor explicitly goes back to `Чернова`;
  // no confirmation dialog and no local state guess. The canonical projection
  // only changes after the server confirms it, and the readiness checkpoint is
  // gone - the Article has to be marked ready again by hand.
  const reopen = useMutation({
    mutationFn: () => reopenArticle(articleId),
    onMutate: () => setTransitionError(""),
    onSuccess: async (projection) => {
      queryClient.setQueryData(queryKeys.article(projection.id), projection);
      setSavedVersion(projection.content.version);
      await invalidateArticleProjections(queryClient, projection.id, projection.story.id);
    },
    onError: async (error) => {
      setTransitionError(
        getErrorMessage(error, "Статията не можа да се върне към чернова. Опитайте отново."),
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.article(articleId), exact: true });
    },
  });

  // «Финализирай`. The idempotency key is created once per attempt and reused
  // for retries, so a double click, a lost response and a transport retry all
  // resolve to the same canonical finalized Article.
  const finalizeKeyRef = useRef<string | null>(null);
  const finalize = useMutation({
    mutationFn: async () => {
      const flushed = flushRef.current ? await flushRef.current() : true;
      if (!flushed) throw new Error("unconfirmed");
      const confirmed = queryClient.getQueryData<ArticleDetail>(queryKeys.article(articleId));
      if (!finalizeKeyRef.current) finalizeKeyRef.current = createIdempotencyKey();
      return finalizeArticle(articleId, confirmed?.content.version ?? 0, finalizeKeyRef.current);
    },
    onMutate: () => setTransitionError(""),
    onSuccess: async (result) => {
      // The server is done: the Article is frozen. The Archive is now the
      // canonical surface, so navigate there instead of showing a dead page.
      queryClient.setQueryData(queryKeys.archiveArticle(result.articleId), result.article);
      await invalidateFinalizedArticle(queryClient, result.articleId, result.article.story.id);
      navigate(result.archivePath);
    },
    onError: async (error) => {
      // A stale checkpoint is not a technical failure: the message says the
      // Article must be reviewed again, and the canonical projection (which may
      // now read `Чернова`) is refetched. Readiness is never re-granted here.
      setTransitionError(
        getErrorMessage(error, "Статията не можа да се финализира. Опитайте отново."),
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.article(articleId), exact: true });
    },
  });

  const canMarkReady = article.availableActions.includes("MARK_READY");
  // Only the server decides which of the two Ready actions exist. A stale
  // checkpoint already projects `Чернова`, so the Ready surface is not shown.
  const isReady = article.state === "ready";
  const canFinalize = isReady && article.availableActions.includes("FINALIZE");
  const transitionPending = reopen.isPending || finalize.isPending;
  // §13/§14: ONE autosave for the whole Article, created once here and shared by
  // the title in the header and the body in the writing column. Two writers
  // would be two optimistic-concurrency writers racing for the same version.
  const autosave = useArticleAutosave({
    article,
    savedVersion,
    registerFlush,
    onSaved: (projection) => {
      queryClient.setQueryData(queryKeys.article(projection.id), projection);
      setSavedVersion(projection.content.version);
    },
  });

  if (article.isFinalized || article.state === null) {
    return <Navigate replace to={`/archive/${encodeURIComponent(article.id)}`} />;
  }
  if (article.state === "preparation") {
    return <PreparationWorkspace
      article={article}
      autosave={autosave}
      editing={editing}
      onEditingChange={setEditing}
    />;
  }
  const facts = article.factsAndSources;
  const missing = article.missingInformation;
  // V1.2-G4.3: the material this Draft was actually written from. A single-source
  // Draft has no confirmed fact to show, but the editor must still see WHICH page
  // it came from and be able to open it - that is what makes the single-source
  // warning checkable instead of merely asserted.
  const opened = (missing && missing.openedSources) || [];

  // §6: the evidence rail is never reserved empty. An Article with nothing to
  // support it gets the full width for writing, because a blank 300px slab
  // beside a textarea is the most wasteful thing this page could do.
  const hasEvidence = facts.length > 0
    || opened.length > 0
    || Boolean(missing && missing.items.length > 0);

  return <div className={`${ui.page} ${ui.articles} ${styles.workspace}`}>
    {/* §7/§16: a compact header — back link, what this is, the title, the state.
        The Story stays one quiet line away, not a second workspace. */}
    <header className={styles.deskHeader}>
      <div className={styles.deskHeaderTop}>
        <Link className={styles.backLink} to="/articles">← Статии</Link>
        <div className={styles.headingLine}>
          <Context>Статия</Context>
          <StatusMarker state={article.state} />
        </div>
      </div>
      {/* §7/§8: the title is the page's own heading and stays directly editable,
          with passive save status and no version or concurrency detail. V1.2-G4.3:
          a Draft is editable on arrival; only `Готова` is calm until reopened. */}
      <ArticleDeskTitle autosave={autosave} editable={!isReady} />
      <p className={styles.linkedStory}>
        История:{" "}
        <Link to={`/stories/${encodeURIComponent(article.story.id)}`}>
          {article.story.title || "Свързана история"}
        </Link>
      </p>
    </header>

    {/* §5/§6: the writing column owns the screen; the rail is supporting only. */}
    <div className={evidenceOpen && hasEvidence ? styles.deskGrid : styles.deskGridSolo}>
      {/* §34: the application shell already owns the single `main` landmark, so the
          writing column is a labelled region inside it. A nested `main` would give
          the page two landmarks and break the structure a screen reader relies on. */}
      <section className={styles.writingColumn} aria-label="Текст на статията">

        {/* §12: once a Draft exists the Focus is a quiet, collapsible block. A
            large textarea above every Draft would compete with the text. */}
        <DraftFocusBlock article={article} />

        <section className={styles.content} aria-labelledby="article-content-heading">
          <div className={styles.contentHeader}>
            <h2 className={styles.contentHeading} id="article-content-heading">
              {contentHeading(article.state)}
            </h2>
            {/* §29: at most ONE emphasised forward action at any moment. */}
            <div className={styles.contentControls}>
              {isReady ? (
                <button
                  className={styles.secondaryAction}
                  type="button"
                  disabled={transitionPending}
                  onClick={() => reopen.mutate()}
                >
                  {reopen.isPending ? "Връща се…" : "Редактирай"}
                </button>
              ) : null}
              {/* V1.2-G4.3: a Draft is DIRECTLY editable. The old «Редактирай»
                  toggle added a step between the editor and their own text on a
                  page that already autosaves, already negotiates a version, and
                  already has exactly one body control. The editor opens a Draft
                  and starts typing. `Готова` stays calm and read-only, and
                  reopening it is still an explicit decision. */}
              {canMarkReady ? (
                <button
                  className={styles.primaryAction}
                  type="button"
                  disabled={ready.isPending}
                  onClick={() => ready.mutate()}
                >
                  {ready.isPending ? "Проверява се…" : "Отбележи като готова"}
                </button>
              ) : null}
              {canFinalize ? (
                <button
                  className={styles.primaryAction}
                  type="button"
                  disabled={transitionPending}
                  onClick={() => finalize.mutate()}
                >
                  {finalize.isPending ? "Финализира се…" : "Финализирай"}
                </button>
              ) : null}
            </div>
          </div>
          {/* V1.2-G4.3: a Draft opens straight into its text - no `Редактирай`
              step. A `Готова` Article stays calm and read-only until the editor
              explicitly reopens it, so a finished text is never one stray
              keystroke away from being changed. */}
          {isReady ? <>
            {/* The title is already the page heading in the header. Repeating it
                above the body printed the same sentence twice on one screen, so
                the read-only view starts at the text itself. */}
            {article.content.body.trim()
              ? <p className={styles.contentBody}>{article.content.body}</p>
              : <p className={styles.contentEmpty}>Още няма текст на статията.</p>}
          </> : <ArticleContentEditor autosave={autosave} />}
          {ready.isPending ? <p className={styles.readyFeedback} role="status" aria-live="polite">
            Проверява се текущата версия.
          </p> : null}
          {readyError ? <p className={styles.readyError} role="alert">{readyError}</p> : null}
          {transitionPending ? <p className={styles.readyFeedback} role="status" aria-live="polite">
            {finalize.isPending ? "Финализира се…" : "Връща се към черновата…"}
          </p> : null}
          {transitionError ? <p className={styles.readyError} role="alert">{transitionError}</p> : null}
        </section>

        {/* §20: warnings are attached to the decision they affect, not collected
            into one large panel. §31: the heading names WHAT TO LOOK AT, never a
            workflow state like «Проверка» — this is not a state, it is a note
            beside the decision. */}
        <section className={styles.readinessBlock} aria-labelledby="article-readiness-heading">
          <h2 className={styles.contentHeading} id="article-readiness-heading">Какво да прегледаш</h2>
          {!article.validation.current ? <p className={styles.warningStale}>
            Проверката на текущия текст не е налична. Прегледайте черновата, преди да я отбележите.
          </p> : null}
          {article.validation.current && article.warnings.length > 0 ? <ul className={styles.warningList}>
            {article.warnings.map((warning) => <li
              className={warningClass(warning)}
              key={warning.id}
            >
              <p className={styles.warningMessage}>{warning.message}</p>
              {warning.affectedText ? <p className={styles.affectedText}>{warning.affectedText}</p> : null}
            </li>)}
          </ul> : null}
          {/*
            V1.2-G4.1 §B3/§C2 — the MATERIAL warnings, above the text audit and in
            their own block. These say what the Draft was written *from* (one
            unconfirmed source, questions still open) and are recomputed by the
            backend from the canonical basis, so they can never go stale. They are
            warnings and not a state: the Article is still `Чернова`, fully
            editable, and the only thing they withhold is `Готова`.
          */}
          {article.draftWarnings.length > 0 ? <ul className={styles.warningList} data-draft-warnings="true">
            {article.draftWarnings.map((warning) => <li className={styles.warningMessage} key={warning}>
              {warning}
            </li>)}
          </ul> : null}
          {article.validation.current && article.warnings.length === 0 && article.draftWarnings.length === 0 ? (
            <p className={styles.noWarnings}>Няма твърдения, които изискват проверка.</p>
          ) : null}
        </section>
      </section>

      {/* §17/§19: the factual support rail — collapsible, and rendered only when
          the Article has something to support it with. */}
      {hasEvidence ? <aside className={styles.evidenceColumn} aria-labelledby="article-evidence-heading">
        <div className={styles.evidenceHeader}>
          <h2 className={styles.evidenceHeading} id="article-evidence-heading">Факти и източници</h2>
          <button
            className={styles.evidenceToggle}
            type="button"
            aria-expanded={evidenceOpen}
            aria-controls="article-evidence-body"
            onClick={() => setEvidenceOpen((open) => !open)}
          >
            {evidenceOpen ? "Скрий източниците" : "Покажи източниците"}
          </button>
        </div>
        <div id="article-evidence-body" hidden={!evidenceOpen}>
          {facts.length > 0 ? <ul className={styles.factList}>
            {facts.map((fact) => {
              const sourceUrl = safeExternalUrl(fact.source.url);
              return <li className={styles.fact} key={fact.id}>
                <p className={styles.factText}>{fact.text}</p>
                <p className={styles.source}>
                  {sourceUrl ? <a
                    className={styles.sourceLink}
                    href={sourceUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {fact.source.name} <span aria-hidden="true">↗</span>
                  </a> : <strong>{fact.source.name}</strong>}
                </p>
              </li>;
            })}
          </ul> : null}
          {/* V1.2-G4.3: what the Draft was written FROM. The panel used to be
              headed «Факти и източници» while showing no fact and no source at
              all on a single-source Draft - the very case the warning talks
              about. Naming the opened publication and linking it makes the
              single-source warning something the editor can actually check. */}
          {opened.length > 0 ? <section className={styles.gapBlock}>
            <h3 className={styles.evidenceSubheading}>Изходен материал</h3>
            <ul className={styles.missingList}>
              {opened.map((source) => {
                const url = safeExternalUrl(source.url);
                return <li className={styles.missingItem} key={source.id}>
                  <p className={styles.missingQuestion}>
                    {url ? <a
                      className={styles.sourceLink}
                      href={url}
                      target="_blank"
                      rel="noreferrer noopener"
                      data-article-origin
                    >
                      {source.name} <span aria-hidden="true">↗</span>
                    </a> : <strong>{source.name}</strong>}
                  </p>
                </li>;
              })}
            </ul>
            {/* §B3: the honest count. One opened page is not corroboration, and
                saying so here keeps the panel and the warning in agreement. */}
            <p className={styles.missingReason}>
              {opened.length === 1
                ? "Един източник · няма независимо потвърждение"
                : `${opened.length} източника · независимо потвърждение не е установено`}
            </p>
          </section> : null}
          {missing && missing.items.length > 0 ? <section className={styles.gapBlock}>
            <h3 className={styles.evidenceSubheading}>Остава непотвърдена информация</h3>
            <ul className={styles.missingList}>
              {missing.items.map((item) => <li className={styles.missingItem} key={item.id}>
                <p className={styles.missingQuestion}>{item.question}</p>
                {item.reason ? <p className={styles.missingReason}>{item.reason}</p> : null}
              </li>)}
            </ul>
          </section> : null}
        </div>
      </aside> : null}
    </div>
  </div>;
}

