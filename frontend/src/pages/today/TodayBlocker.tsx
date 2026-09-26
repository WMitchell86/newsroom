import styles from "./Today.module.css";

/**
 * V1.2-G1 §18-§21: the one place a Today row explains itself.
 *
 * **The rule this component exists to enforce:** the text is whatever the
 * backend said, rendered verbatim. The frontend never composes a warning, never
 * summarises a reason code, and above all never judges a publisher.
 *
 * The distinction the system actually draws is between *who published* and
 * *what was verified*: a source was discovered, a publisher identity exists, a
 * factual-authority flag exists, a page was actually opened, a canonical final
 * URL was reached, facts were confirmed, and a blocking gap may remain. A
 * perfectly reputable publisher can still be the reason a Story has no evidence
 * — because the page was never opened, or a Google News redirect never
 * resolved, or nothing was extracted. So generic wording like «Нужен е надежден
 * отворен източник» would be false in both directions, and is never written
 * here.
 *
 * §20 follows from the same rule: there is deliberately no `Надежден` /
 * `Verified` / `Trusted` badge. `factual_authority` is an internal evidence
 * property about a publisher; it says nothing about whether *this* Story has a
 * sufficient evidence basis, and a badge would make the editor read it as if it
 * did.
 */
export function TodayBlocker({ message }: { message: string }) {
  return (
    <p className={styles.blocker} role="alert">
      {/*
        Decorative only: the sentence carries the meaning, so the glyph is hidden
        from assistive technology rather than announced as a second message.
      */}
      <span className={styles.blockerMark} aria-hidden="true">
        !
      </span>
      <span className={styles.blockerText}>{message}</span>
    </p>
  );
}
