import { useId, useState, type ReactNode, type Ref } from "react";
import type { ArticleState } from "../api/dto";
import { articleStateLabels } from "./editorLabels";
import { getErrorMessage } from "./errorMessage";
import styles from "./ui.module.css";

export function PageHeader({ kicker, title, lede, article = false, headingRef }: {
  kicker: string;
  title: string;
  lede?: string;
  article?: boolean;
  headingRef?: Ref<HTMLHeadingElement>;
}) {
  return <header className={styles.header}>
    <p className={styles.kicker}>{kicker}</p>
    <h1 ref={headingRef} tabIndex={headingRef ? -1 : undefined} className={article ? styles.articleTitle : styles.title}>{title}</h1>
    {lede ? <p className={styles.lede}>{lede}</p> : null}
  </header>;
}

export function StatusMarker({ state }: { state: ArticleState }) {
  return <span className={`${styles.statusMarker} ${state === "ready" ? styles.statusReady : ""}`}>
    {articleStateLabels[state]}
  </span>;
}

export function Context({ children }: { children: ReactNode }) {
  return <span className={styles.context}>{children}</span>;
}

export function Section({ title, meta, children }: { title: string; meta?: string; children: ReactNode }) {
  return <section className={styles.section}>
    <div className={styles.sectionHeader}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {meta ? <span className={styles.sectionMeta}>{meta}</span> : null}
    </div>
    {children}
  </section>;
}

export function Disclosure({ label, children, defaultOpen = false }: { label: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return <div className={styles.disclosure}>
    <button className={styles.disclosureButton} type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}>
      <span>{label}</span><span aria-hidden="true">{open ? "−" : "+"}</span>
    </button>
    <div id={id} className={styles.disclosureBody} hidden={!open}>{children}</div>
  </div>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className={styles.empty}>{children}</p>;
}

export function ErrorState({ title = "Съдържанието не можа да се зареди", error, onRetry }: { title?: string; error: unknown; onRetry?: () => void }) {
  return <div className={styles.error} role="alert">
    <h2 className={styles.errorTitle}>{title}</h2>
    <p className={styles.errorMessage}>{getErrorMessage(error)}</p>
    {onRetry ? <button className={styles.retry} type="button" onClick={onRetry}>Опитайте отново</button> : null}
  </div>;
}

export function LoadingState({ label = "Зареждане…" }: { label?: string }) {
  return <div className={styles.loading} role="status" aria-live="polite">
    <div className={styles.loadingLines} aria-hidden="true">
      <span className={styles.loadingLine} /><span className={styles.loadingLine} /><span className={styles.loadingLine} />
    </div>
    <span>{label}</span>
  </div>;
}
