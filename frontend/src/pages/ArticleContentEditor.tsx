import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, getArticle, updateArticleContent } from "../api/client";
import { queryKeys } from "../api/queries";
import type { ArticleContent, ArticleProjection } from "../api/dto";
import { Context } from "../shared/EditorPrimitives";
import styles from "./ArticleWorkspace.module.css";

const AUTOSAVE_DELAY_MS = 800;

type SaveStatus = "idle" | "saving" | "saved" | "error" | "conflict";

function sameContent(left: ArticleContent, right: ArticleContent): boolean {
  return left.title === right.title && left.body === right.body;
}

export function ArticleContentEditor({
  article,
  onSaved,
  savedVersion,
  registerFlush,
}: {
  article: ArticleProjection;
  onSaved?: (projection: ArticleProjection) => void;
  savedVersion?: number | null;
  registerFlush?: (flush: (() => Promise<boolean>) | null) => void;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(article.content.title);
  const [body, setBody] = useState(article.content.body);
  const [status, setStatus] = useState<SaveStatus>(
    savedVersion === article.content.version ? "saved" : "idle",
  );
  const [serverConflict, setServerConflict] = useState<ArticleProjection | null>(null);
  const [navigationWarning, setNavigationWarning] = useState("");

  const localRef = useRef(article.content);
  const confirmedRef = useRef(article.content);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightRef = useRef(false);
  const inFlightPromiseRef = useRef<Promise<boolean> | null>(null);
  const dirtyRef = useRef(false);
  const mountedRef = useRef(true);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const flush = useCallback(async (force = false): Promise<boolean> => {
    clearTimer();
    // A save that is already running is awaited, never raced and never reported
    // as "unconfirmed": the readiness checkpoint must be sent against the
    // version the server actually holds, so the parent can rely on `true`.
    if (inFlightRef.current && inFlightPromiseRef.current) await inFlightPromiseRef.current;
    if (inFlightRef.current || (serverConflict && !force)) return !dirtyRef.current;
    if (!dirtyRef.current) return true;
    if (!localRef.current.title.trim()) {
      setStatus("error");
      return false;
    }
    inFlightRef.current = true;
    setStatus("saving");
    const run = (async (): Promise<boolean> => {
      try {
        while (dirtyRef.current && (!serverConflict || force)) {
          const snapshot = { ...localRef.current };
          const projection = await updateArticleContent(
            article.id,
            confirmedRef.current.version,
            snapshot.title,
            snapshot.body,
          );
          confirmedRef.current = { ...projection.content };
          queryClient.setQueryData(queryKeys.article(article.id), projection);
          onSaved?.(projection);
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["articles"] }),
            queryClient.invalidateQueries({ queryKey: queryKeys.today, exact: true }),
            queryClient.invalidateQueries({ queryKey: queryKeys.story(article.story.id), exact: true }),
          ]);
          if (sameContent(localRef.current, snapshot)) dirtyRef.current = false;
        }
        if (mountedRef.current) setStatus(dirtyRef.current ? "idle" : "saved");
        return !dirtyRef.current;
      } catch (error) {
        if (!mountedRef.current) return false;
        if (error instanceof ApiError && error.code === "ARTICLE_VERSION_CONFLICT") {
          try {
            const canonical = await getArticle(article.id);
            setServerConflict(canonical);
            setStatus("conflict");
          } catch {
            setStatus("error");
          }
        } else {
          setStatus("error");
        }
        return false;
      } finally {
        inFlightRef.current = false;
        inFlightPromiseRef.current = null;
      }
    })();
    inFlightPromiseRef.current = run;
    return run;
  }, [article.id, article.story.id, clearTimer, onSaved, queryClient, serverConflict]);


  const change = useCallback((nextTitle: string, nextBody: string) => {
    localRef.current = { ...localRef.current, title: nextTitle, body: nextBody };
    dirtyRef.current = !sameContent(localRef.current, confirmedRef.current);
    setTitle(nextTitle);
    setBody(nextBody);
    setStatus((current) => current === "conflict" ? current : dirtyRef.current ? "idle" : current);
    clearTimer();
    if (dirtyRef.current) timerRef.current = setTimeout(() => void flush(), AUTOSAVE_DELAY_MS);
  }, [clearTimer, flush]);

  useEffect(() => () => {
    mountedRef.current = false;
    clearTimer();
  }, [clearTimer]);

  // The readiness checkpoint binds to the CONFIRMED canonical version, so the
  // parent must be able to await a pending autosave before it sends it.
  useEffect(() => {
    if (!registerFlush) return;
    registerFlush(() => flush());
    return () => registerFlush(null);
  }, [flush, registerFlush]);

  useEffect(() => {
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current && !inFlightRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, []);

  useEffect(() => {
    const guardInternalLink = (event: MouseEvent) => {
      if (!dirtyRef.current && !inFlightRef.current) return;
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(target instanceof HTMLAnchorElement)) return;
      const destination = new URL(target.href, window.location.href);
      if (destination.origin !== window.location.origin) return;
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      void flush().then((saved) => {
        if (saved) window.location.assign(destination.href);
        else setNavigationWarning("Има незапазени локални промени. Опитайте отново, преди да навигирате.");
      });
    };
    document.addEventListener("click", guardInternalLink, true);
    return () => document.removeEventListener("click", guardInternalLink, true);
  }, [flush]);

  const useLocalChanges = () => {
    if (!serverConflict) return;
    confirmedRef.current = { ...serverConflict.content };
    setServerConflict(null);
    setStatus("idle");
    dirtyRef.current = true;
    void flush(true);
  };

  const loadServerVersion = () => {
    if (!serverConflict) return;
    const canonical = { ...serverConflict.content };
    localRef.current = canonical;
    confirmedRef.current = { ...canonical };
    setTitle(canonical.title);
    setBody(canonical.body);
    setServerConflict(null);
    setStatus("saved");
    dirtyRef.current = false;
    queryClient.setQueryData(queryKeys.article(article.id), serverConflict);
  };

  return <div className={styles.editorShell}>
    <div className={styles.editorToolbar}>
      <Context>Работно съдържание</Context>
      <div className={styles.editorFeedback} role="status" aria-live="polite">
        {status === "saving" ? "Запазване…" : status === "saved" ? "Запазено" : null}
        {status === "error" ? <span role="alert">Запазването не успя.</span> : null}
      </div>
    </div>
    <label className={styles.editorLabel} htmlFor="article-working-title">Заглавие</label>
    <input
      className={styles.editorTitle}
      id="article-working-title"
      value={title}
      onChange={(event) => change(event.target.value, body)}
      onBlur={() => void flush()}
    />
    {/* V1.1-C: exactly ONE body control. This component used to render a second
        textarea bound to the same `body` state, under the same DOM id, which
        made the labelled control a duplicate and every test drove the orphan.
        Autosave, flush and conflict handling are unchanged — only the duplicate
        control and its duplicated retry/warning blocks are gone. */}
    <label className={styles.editorLabel} htmlFor="article-working-body">Текст на статията</label>
    <textarea
      className={styles.editorBody}
      id="article-working-body"
      value={body}
      onChange={(event) => change(title, event.target.value)}
      onBlur={() => void flush()}
    />
    {status === "error" && !serverConflict ? (
      <button className={styles.autosaveRetry} type="button" onClick={() => void flush()}>Опитайте отново</button>
    ) : null}
    {navigationWarning ? <p className={styles.navigationWarning} role="alert">{navigationWarning}</p> : null}
    {serverConflict ? <section className={styles.conflict} role="alert" aria-labelledby="article-conflict-title">
      <h3 id="article-conflict-title">Черновата е променена в друга сесия.</h3>
      <p>Локалните промени са запазени.</p>
      <div className={styles.conflictActions}>
        <button type="button" onClick={useLocalChanges}>Използвай моите промени</button>
        <button type="button" onClick={loadServerVersion}>Зареди запазената версия</button>
      </div>
    </section> : null}
  </div>;
}
