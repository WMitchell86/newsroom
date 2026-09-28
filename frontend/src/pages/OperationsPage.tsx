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

function scopeLabel(scope: string): { articleId: string | null; kind: string } {
  const match = /^article-draft:(art_[a-z0-9]+(?:_[0-9]+)?)$/.exec(scope);
  if (match?.[1]) return { articleId: match[1], kind: "Чернова" };
  const story = /^s[a-zA-Z0-9_-]+$/.exec(scope);
  if (story) return { articleId: null, kind: "Проучване" };
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
            return (
              <li key={op.operationToken} className={styles.row} data-status={op.status}>
                <div className={styles.head}>
                  <span className={styles.status} data-status={op.status}>
                    {STATUS_LABELS[op.status]}
                  </span>
                  <span className={styles.kind}>
                    {kind}
                    {articleId ? (
                      <a href={`/articles/${articleId}`}>{articleId}</a>
                    ) : null}
                  </span>
                </div>
                {op.error ? (
                  <p className={styles.reason} data-status={op.status}>
                    {op.error}
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
