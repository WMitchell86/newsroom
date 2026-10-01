import { useQuery } from "@tanstack/react-query";
import { getOperations } from "../api/client";
import type { OperationSummary } from "../api/dto";
import styles from "./OperationsPage.module.css";

/**
 * V1.2-G4.6: what the editor asked for, and what became of it.
 *
 * Before this page the only trace of a request was the 202 handle it returned,
 * and there was no list of handles. Four drafts meant four opaque tokens and
 * no way to learn afterwards whether any of them had run, failed, or been lost
 * when the server restarted - which is exactly the question this answers.
 *
 * Everything here is rendered from the server's own record. A row whose status
 * is `failed` shows the reason the server stored, not a summary invented here:
 * "Source unavailable" taught us that a confident wrong sentence is worse than
 * an ugly true one.
 */

const STATUS_LABELS: Record<OperationSummary["status"], string> = {
  pending: "Чака",
  running: "В момента върви",
  succeeded: "Готово",
  failed: "Провал",
};

/**
 * V1.2-G4.36: the command finished and produced nothing.
 *
 * Not a fourth registry status — `status` stays whatever the worker did. This
 * is the COMMAND's own word for a refusal, and it is the one the editor needs,
 * because "Готово" over an empty result is the sentence this page was written
 * to stop telling.
 */
const REFUSED_OUTCOME = "needs_attention";
const REFUSED_LABEL = "Не се получи";

const ARTICLE_ID = /(art_[a-z0-9]+(?:_[0-9]+)?)$/;

function scopeLabel(scope: string): { articleId: string | null; kind: string } {
  // Every scope the application actually creates, in the editor's own words.
  // A Quick Draft and a Rewrite used to fall through to the generic "Операция",
  // so the page that exists to answer "what happened to what I asked for" could
  // not even name them — and the Quick Draft scope string carries the STORY id,
  // which is not a link.
  const draftId = /^article-draft:(.+)$/.exec(scope)?.[1];
  if (draftId && ARTICLE_ID.test(draftId)) return { articleId: draftId, kind: "Чернова" };
  const rewriteId = /^article-rewrite:(.+)$/.exec(scope)?.[1];
  if (rewriteId && ARTICLE_ID.test(rewriteId))
    return { articleId: rewriteId, kind: "Пренапиши" };
  if (/^quick-draft:.+$/.test(scope)) return { articleId: null, kind: "Чернова по история" };
  if (scope === "today-refresh") return { articleId: null, kind: "Обновяване на новините" };
  if (/^s[a-zA-Z0-9_-]+$/.test(scope)) return { articleId: null, kind: "Проучване" };
  return { articleId: null, kind: "Операция" };
}

export function OperationsPage() {
  const query = useQuery({
    queryKey: ["operations"],
    queryFn: getOperations,
    refetchInterval: 5000,
  });

  const operations = query.data?.operations ?? [];

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1>Операции</h1>
        <p className={styles.lead}>
          Всичко, което сте поръчали, и какво се е случило с него. Списъкът
          обхваща последните операции на сървъра; при рестарт тези, които са
          били в движение, се показват като прекъснати, а не изчезват.
        </p>
      </header>

      {query.isLoading && <p className={styles.note}>Зареждане…</p>}

      {query.isError && (
        <p className={styles.error} role="alert">
          Списъкът с операции не можа да се зареди. Сървърът може да е спрял —
          провери лога в терминала, където стартира.
        </p>
      )}

      {query.isSuccess && operations.length === 0 && (
        <p className={styles.note}>
          Няма записани операции. Това значи, че сървърът няма история — не че
          нищо е било поръчано.
        </p>
      )}

      {operations.length > 0 && (
        <ul className={styles.list}>
          {operations.map((op) => {
            const { articleId, kind } = scopeLabel(op.storyId);
            // V1.2-G4.36: a refusal is what the editor needs to see, and it is
            // the COMMAND's answer, not the worker's. The existing `failed`
            // styling carries it, so no new design token is invented here.
            const refused = op.outcome === REFUSED_OUTCOME;
            const state = refused ? "failed" : op.status;
            const reason = op.error || (refused ? op.outcomeMessage ?? "" : "");
            return (
              <li key={op.operationToken} className={styles.row} data-status={state}>
                <div className={styles.head}>
                  <span className={styles.status} data-status={state}>
                    {refused ? REFUSED_LABEL : STATUS_LABELS[op.status]}
                  </span>
                  <span className={styles.kind}>
                    {kind}
                    {articleId ? (
                      <a href={`/articles/${articleId}`}>{articleId}</a>
                    ) : null}
                  </span>
                </div>
                {reason ? (
                  <p className={styles.reason} data-status={state}>
                    {reason}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
