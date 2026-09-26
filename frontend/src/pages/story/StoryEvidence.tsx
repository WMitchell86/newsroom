import type { StoryDetail } from "../../api/dto";
import { safeExternalUrl } from "../../shared/safeNavigation";
import { Section } from "../../shared/EditorPrimitives";
import { confirmedFacts, hasEvidenceBasis } from "./storyView";
import styles from "./Story.module.css";

export interface StoryEvidenceProps {
  story: StoryDetail;
}

/**
 * V1.2-G2 §10/§11/§12/§13: one editorial block — "Факти и източници".
 *
 * Facts and their sources are one thing, so they are one block: each confirmed
 * statement with the source directly under it, separated by a hairline rather
 * than boxed in a card. The source visibly belongs to the statement it supports.
 *
 * Three things this block deliberately never shows:
 *
 *   * evidence ids, packet ids, claim locators, `scope`-as-an-enum, or any
 *     authority value — the editor reads a newsroom note, not a database row;
 *   * a trust label. A publisher can be perfectly reputable and still be a
 *     reason this Story has no evidence, because the page was never opened. The
 *     block therefore states what a source *is* in this Story — where the
 *     statement came from — and never whether the publisher is reliable;
 *   * an empty state. With no confirmed facts there is nothing to say here, so
 *     `StoryWorkspace` renders no block at all. "No facts" on an unassessed
 *     Story means nobody has looked, and printing an empty Facts panel would
 *     read as a clean basis.
 *
 * A source link is rendered only for a URL the backend actually opened and
 * which parses as http(s). A discovery-only URL is never turned into an
 * evidence link here, and a canonical URL is never reconstructed in React.
 */
export function StoryEvidence({ story }: StoryEvidenceProps) {
  const facts = confirmedFacts(story);
  if (!hasEvidenceBasis(story)) return null;

  return (
    <Section title="Факти и източници" meta={String(facts.length)}>
      <ul className={styles.factList}>
        {facts.map((fact) => {
          const url = safeExternalUrl(fact.source.url);
          return (
            <li className={styles.fact} key={fact.id}>
              <p className={styles.factText}>{fact.text}</p>
              <p className={styles.sourceLine}>
                {url ? (
                  <a
                    className={styles.sourceLink}
                    href={url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {fact.source.name}
                  </a>
                ) : (
                  fact.source.name
                )}
                {fact.scope === "background" ? " · фонови контекст" : " · отворен източник"}
              </p>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
