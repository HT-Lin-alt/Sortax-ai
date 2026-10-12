import { ShieldCheck } from "lucide-react";

import type { components } from "../api/generated-types";
import styles from "./messages.module.css";

type SummaryConfirmation = components["schemas"]["SummaryConfirmationContent"];

export function SummaryConfirmationMessage({
  busy = false,
  content,
  onDecision,
}: {
  readonly busy?: boolean;
  readonly content: SummaryConfirmation;
  readonly onDecision?: ((requested: boolean) => void | Promise<void>) | undefined;
}) {
  const disabled = busy || onDecision === undefined;
  return (
    <article aria-busy={busy} className={styles.featureCard}>
      <div className={styles.confirmationPrompt}>
        <ShieldCheck aria-hidden="true" size={21} />
        <div><p className={styles.eyebrow}>Optional summary</p><h2 className={styles.standalonePrompt}>{content.prompt}</h2></div>
      </div>
      <div className={styles.confirmationActions}>
        <button disabled={disabled} onClick={() => { void onDecision?.(false); }} type="button">No, thanks</button>
        <button disabled={disabled} onClick={() => { void onDecision?.(true); }} type="button">Yes, create summary</button>
      </div>
    </article>
  );
}
