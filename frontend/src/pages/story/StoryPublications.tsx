import { useId, useState } from "react";
import type { StoryDetail } from "../../api/dto";
import { formatDate } from "../../shared/editorLabels";
import { safeExternalUrl } from "../../shared/safeNavigation";
import { Section } from "../../shared/EditorPrimitives";
import {
  PUBLICATIONS_PREVIEW,
  developmentPublicationIds,
  hasHiddenPublications,
  visiblePublications,
} from "./storyView";
import styles from "./Story.module.css";

export interface StoryPublicationsProps {
  story: StoryDetail;
}

/**
 * V1.2-G2 §18/§19/§20/§21: "Публикации" — which publications are grouped into
 * this Story.
 *
 * This is **not** "Факти и източници" and the page must never let the two blur
 * into each other. A publication here is a member of the Story that the grouping
 * decided to put here; it is not a confirmed fact, its page is not part of the
 * opened evidence basis, and nothing about a publisher's reputation is claimed.
 * The section answers one question — "which publications are in this Story?" —
 * and the evidence block answers another — "what is confirmed?".
 *
 * It stays compact: a list, not cards, newest first. A Story with seventeen
 * grouped publications shows a working set and one control that reveals the
 * rest, because the whole list is already in the payload and a long Story must
 * not push the confirmed facts off the screen. There is no new endpoint and no
 * new pagination for this.
 */
export function StoryPublications({ story }: StoryPublicationsProps) {
  const [expanded, setExpanded] = useState(false);
  const chronologyId = useId();
  const [chronologyOpen, setChronologyOpen] = useState(false);
  const publications = story.publications ?? [];
  if (!publications.length) return null;

  const rows = visiblePublications(publications, expanded);
  const developmentIds = developmentPublicationIds(story);
  const hidden = hasHiddenPublications(publications, expanded);
  const chronology = story.chronology ?? [];

  return (
    <Section title="Публикации" meta={String(publications.length)}>
      <ul className={styles.publicationList}>
        {rows.map((publication) => {
          const url = safeExternalUrl(publication.url);
          return (
            <li className={styles.publication} key={publication.id}>
              <p className={styles.publicationTitle}>
                {url ? (
                  <a href={url} target="_blank" rel="noreferrer noopener">
                    {publication.title}
                  </a>
                ) : (
                  publication.title
                )}
              </p>
              <p className={styles.publicationMeta}>
                <span>{publication.source.name}</span>
                <span>Публикувана: {formatDate(publication.publishedAt, false)}</span>
                {developmentIds.has(publication.id) ? (
                  // §21: a member the backend classified as a development is
                  // identifiable and nothing more. No new Story state.
                  <span className={styles.developmentTag}>Ново развитие</span>
                ) : null}
              </p>
            </li>
          );
        })}
      </ul>
      {hidden ? (
        <button
          className={styles.showAll}
          type="button"
          onClick={() => setExpanded(true)}
        >
          {`Покажи всички ${publications.length} публикации`}
        </button>
      ) : null}

      {expanded && publications.length > PUBLICATIONS_PREVIEW ? (
        <button className={styles.showAll} type="button" onClick={() => setExpanded(false)}>
          {`Покажи първите ${PUBLICATIONS_PREVIEW} публикации`}
        </button>
      ) : null}

      {/* §20: the canonical chronology is preserved, and deliberately the
          quietest thing on the page. It is not a new timeline component. */}
      {chronology.length ? (
        <div className={styles.chronology}>
          <button
            className={styles.chronologyToggle}
            type="button"
            aria-expanded={chronologyOpen}
            aria-controls={chronologyId}
            onClick={() => setChronologyOpen((open) => !open)}
          >
            <span aria-hidden="true">{chronologyOpen ? "−" : "+"}</span>
            {`Хронология (${chronology.length})`}
          </button>
          <ol id={chronologyId} className={styles.chronologyList} hidden={!chronologyOpen}>
            {chronology.map((event) => (
              <li
                className={styles.event}
                key={`${event.publicationId}-${event.at}-${event.title}`}
              >
                <span>{formatDate(event.at)}</span>
                <span className={styles.eventTitle}>{event.title}</span>
                {event.kind === "NEW_DEVELOPMENT" ? (
                  <span className={styles.developmentTag}>Ново развитие</span>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </Section>
  );
}
