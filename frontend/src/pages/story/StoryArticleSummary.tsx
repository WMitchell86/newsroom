import { Link } from "react-router-dom";
import type { ArticleReference, StoryDetail } from "../../api/dto";
import { formatDate } from "../../shared/editorLabels";
import { Section } from "../../shared/EditorPrimitives";
import { articleStateLabel } from "./storyView";
import styles from "./Story.module.css";

export interface StoryArticleSummaryProps {
  story: StoryDetail;
}

function articleHref(article: ArticleReference): string {
  // A finalized Article has left the active workflow: its traceability link
  // points at the read-only Archive view, never at a dead workspace.
  if (article.finalizedAt) return `/archive/${encodeURIComponent(article.id)}`;
  return `/articles/${encodeURIComponent(article.id)}`;
}

/**
 * V1.2-G2 §22/§23/§24: the Story's Articles, as context — not as a second
 * Article editor.
 *
 * A Story with no Article renders nothing here: there is no empty panel to look
 * at, and the forward action already sits in the header as the one strong
 * control. A Story with several Articles shows the list and lets the editor
 * choose — nothing is marked primary, sorted first, or guessed at, because the
 * backend has no such opinion and the page must not invent one.
 *
 * The state word is the canonical one from the projection, and a finalized
 * Article says so instead of inheriting a state it no longer has.
 */
export function StoryArticleSummary({ story }: StoryArticleSummaryProps) {
  if (!story.relatedArticles.length) return null;

  return (
    <Section title="Статии" meta={String(story.relatedArticles.length)}>
      <ul className={styles.articleList}>
        {story.relatedArticles.map((article) => (
          <li className={styles.article} key={article.id}>
            <h3 className={styles.articleTitle}>
              <Link to={articleHref(article)}>{article.title ?? "Свързана статия"}</Link>
            </h3>
            <p className={styles.articleMeta}>
              <span className={styles.articleState}>
                {article.finalizedAt
                  ? "В архива"
                  : articleStateLabel(article.state) ?? "Статия"}
              </span>
              {article.updatedAt && !article.finalizedAt ? (
                <span>Обновена: {formatDate(article.updatedAt)}</span>
              ) : null}
              <Link to={articleHref(article)}>Отвори</Link>
            </p>
          </li>
        ))}
      </ul>
    </Section>
  );
}
