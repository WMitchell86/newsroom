import { useQuery } from "@tanstack/react-query";
import { getOperations } from "../api/client";
import type { OperationSummary } from "../api/dto";
import { formatOperationWhen } from "../shared/editorLabels";
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

/**
 * V1.2-G4.38: the row's wording comes from the SERVER now.
 *
 * This function used to reverse-engineer the kind from the scope string and
 * build the link itself. That second copy of the scope list was the defect:
 * measured on the six scope shapes the application actually creates, only 2
 * produced a link — `quick-draft:s…` and the bare Story id used by research
 * both rendered nothing clickable, and `desk-quick-drafts` fell through every
 * branch to the generic «Операция». The Story id was in the string the whole
 * time; the link simply was not made, on the strength of a comment claiming a
 * Story id "is not a link". `stories/:storyId` has existed the entire time.
 *
 * So the client no longer decides. `topicHref` is empty exactly when the server
 * has no single subject to open — a newsroom-wide action — and that is the one
 * case where a missing link is the honest answer rather than a bug.
 */
function rowKind(op: OperationSummary): string {
  return op.kind?.trim() || "Операция";
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
            // V1.2-G4.36: a refusal is what the editor needs to see, and it is
            // the COMMAND's answer, not the worker's. The existing `failed`
            // styling carries it, so no new design token is invented here.
            const refused = op.outcome === REFUSED_OUTCOME;
            const state = refused ? "failed" : op.status;
            const reason = op.error || (refused ? op.outcomeMessage ?? "" : "");
            // V1.2-G4.38. `finishedAt` is the honest "when this stopped" for
            // finished work and is empty for a job still running — so a pending
            // row shows when it STARTED and never a finish time it does not
            // have. Using the start time everywhere would misdate every row by
            // however long the work took.
            const when = formatOperationWhen(
              op.status === "pending" || op.status === "running" ? op.startedAt : op.finishedAt || op.startedAt,
            );
            return (
              <li key={op.operationToken} className={styles.row} data-status={state}>
                <div className={styles.head}>
                  <span className={styles.status} data-status={state}>
                    {refused ? REFUSED_LABEL : STATUS_LABELS[op.status]}
                  </span>
                  <span className={styles.kind}>{rowKind(op)}</span>
                  {/*
                    V1.2-G4.38: the topic is the link, and its text is the real
                    headline. Before this the anchor text was the internal id
                    (`art_85e69497b45cdbe`), which told the editor nothing they
                    could act on.
                  */}
                  {op.topic ? (
                    op.topicHref ? (
                      <a className={styles.topic} href={op.topicHref}>
                        {op.topic}
                      </a>
                    ) : (
                      <span className={styles.topic}>{op.topic}</span>
                    )
                  ) : null}
                  {/*
                    An explicit "няма дата", not a dash: a row the server never
                    stamped is a different fact from a row that is merely old,
                    and only one of them should look unusual.
                  */}
                  <span className={styles.when}>{when ?? "няма дата"}</span>
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
