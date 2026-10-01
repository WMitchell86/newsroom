import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { decideFeedbackProposal } from "../api/client";
import type { FeedbackInstruction, FeedbackProposal } from "../api/dto";
import { feedbackOptions, queryKeys } from "../api/queries";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section } from "../shared/EditorPrimitives";
import { getErrorMessage } from "../shared/errorMessage";
import styles from "./FeedbackSettingsPage.module.css";

/**
 * V1.2-G4.3 §G — `Настройки → Редакционно обучение`.
 *
 * The controlled learning loop had a service and a CLI but no surface an editor
 * could use; this page is that surface, and it owns no state of its own. Every
 * word on it comes from `/api/v1/settings/feedback`, which runs the same
 * deterministic analyzer the CLI runs.
 *
 * What an editor can do, and nothing more:
 *   - see how much feedback has accumulated and whether it is enough;
 *   - read the recurring patterns the analyzer found, with the editor comments
 *     that support each one;
 *   - approve or reject ONE proposal — the only thing in the product that can
 *     make a learned instruction active.
 *
 * Two things this page deliberately does NOT do: it never lets the client send
 * the instruction text (the server decides the pattern it actually found), and
 * it never offers a decision below the threshold. A conflict is shown as a
 * question, never with buttons — a conflict is not an approvable rule.
 */

/** The one technical enum a proposal carries, in the editor's own words. */
const TARGET_LABELS: Record<string, string> = {
  GENERAL_DRAFT_INSTRUCTION: "Обща инструкция за писане",
  SITE_DNA: "Профил на изданието",
  VOICE: "Стил на гласа",
  MODE: "Режим на писане",
};

function targetLabel(target: string): string {
  return TARGET_LABELS[target] ?? "Правило за писане";
}

function ProposalCard({
  proposal,
  pending,
  onDecide,
}: {
  proposal: FeedbackProposal;
  pending: boolean;
  onDecide: (approved: boolean) => void;
}) {
  const isConflict = proposal.status === "conflict";
  return (
    <li className={styles.card} data-feedback-proposal={proposal.patternId} data-feedback-state={proposal.status}>
      <div className={styles.cardHead}>
        <h3 className={styles.cardTitle}>{proposal.label}</h3>
        <span className={styles.support}>
          Подкрепа: {proposal.support} от {proposal.total}
        </span>
      </div>
      <p className={styles.suggestion}>{proposal.suggestedInstruction}</p>
      <p className={styles.target}>Прилага се към: {targetLabel(proposal.target)}</p>
      {proposal.examples.length ? (
        <ul className={styles.examples}>
          {proposal.examples.map((example, index) => (
            <li className={styles.example} key={index}>
              „{example}“
            </li>
          ))}
        </ul>
      ) : null}
      {isConflict ? (
        // A conflict is two editors asking for opposite things. There is no
        // instruction to approve — the editor must choose the priority first.
        <p className={styles.conflict} role="note">
          Редакторите искат противоположни неща. Това е въпрос, а не правило — първо изберете
          приоритет.
        </p>
      ) : (
        <div className={styles.actions}>
          <button
            className={styles.approve}
            type="button"
            disabled={pending}
            data-feedback-action="approve"
            onClick={() => onDecide(true)}
          >
            Одобри
          </button>
          <button
            className={styles.reject}
            type="button"
            disabled={pending}
            data-feedback-action="reject"
            onClick={() => onDecide(false)}
          >
            Отхвърли
          </button>
        </div>
      )}
    </li>
  );
}

function ActiveRule({ rule }: { rule: FeedbackInstruction }) {
  return (
    <li className={styles.rule} data-feedback-rule={rule.patternId} data-rule-approved={rule.approved}>
      <p className={styles.ruleText}>{rule.instruction}</p>
      <p className={styles.ruleMeta}>
        {rule.approved ? "Активно" : "Отхвърлено"} · {targetLabel(rule.target)} · подкрепа{" "}
        {rule.support}
      </p>
    </li>
  );
}

export function FeedbackSettingsPage() {
  const query = useQuery(feedbackOptions());
  const queryClient = useQueryClient();
  const decide = useMutation({
    mutationFn: ({ patternId, approved }: { patternId: string; approved: boolean }) =>
      decideFeedbackProposal(patternId, approved),
    onSuccess: async () => {
      // The server returns the new state, but the canonical read is what the
      // page renders, so a refetch keeps this screen honest about what changed.
      await queryClient.invalidateQueries({ queryKey: queryKeys.feedback });
    },
  });

  if (query.isPending) return <LoadingState label="Зареждане на редакционното обучение…" />;
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  const status = query.data;
  const active = status.instructions.filter((rule) => rule.approved);
  const retired = status.instructions.filter((rule) => !rule.approved);
  const decisionError = decide.error
    ? getErrorMessage(decide.error, "Решението не можа да бъде записано. Опитайте отново.")
    : null;

  return (
    <div className={styles.page} data-feedback-eligible={status.eligible}>
      <PageHeader
        kicker="Настройки"
        title="Редакционно обучение"
        lede="Правилата тук се предлагат от повтарящи се редакционни забележки. Моделът не може да променя инструкциите си сам — едно правило става активно само след човешко одобрение."
      />

      <Section title="Състояние">
        <p className={styles.status}>
          {status.pending} от {status.threshold} необходими записа.
        </p>
        <p className={styles.statusNote}>
          {status.eligible
            ? "Има достатъчно записи за анализ."
            : "Анализът се задейства, когато се съберат достатъчно записи. Дотук нищо не се променя."}
        </p>
      </Section>

      {decisionError ? (
        <p className={styles.decisionError} role="alert">
          {decisionError}
        </p>
      ) : null}

      <Section
        title="Предложения"
        meta={status.eligible ? `${status.proposals.length} предложения` : "очаква се"}
      >
        {status.proposals.length ? (
          <ul className={styles.cards}>
            {status.proposals.map((proposal) => (
              <ProposalCard
                key={proposal.patternId}
                proposal={proposal}
                pending={decide.isPending}
                onDecide={(approved) =>
                  decide.mutate({ patternId: proposal.patternId, approved })
                }
              />
            ))}
          </ul>
        ) : (
          <EmptyState>
            {status.eligible
              ? "Няма открит повтарящ се модел в събраните забележки."
              : "Още няма предложения. Те се появяват след като се съберат достатъчно записи."}
          </EmptyState>
        )}
      </Section>

      <Section title="Активни правила" meta={`${active.length} активни`}>
        {status.instructions.length ? (
          <ul className={styles.rules}>
            {[...active, ...retired].map((rule) => (
              <ActiveRule key={rule.patternId} rule={rule} />
            ))}
          </ul>
        ) : (
          <EmptyState>Все още няма одобрени редакционни правила.</EmptyState>
        )}
      </Section>
    </div>
  );
}
