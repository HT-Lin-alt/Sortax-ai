import { Search } from "lucide-react";

import styles from "./messages.module.css";

export function ThinkingMessage() {
  return (
    <article aria-busy="true" aria-label="Finding relevant ATO guidance" className={styles.thinking}>
      <span aria-hidden="true" className={styles.thinkingIcon}><Search size={17} /></span>
      <div>
        <strong>Checking the details</strong>
        <p>Finding the most relevant ATO guidance for your selections…</p>
      </div>
      <span aria-hidden="true" className={styles.pulse}><i /><i /><i /></span>
    </article>
  );
}
