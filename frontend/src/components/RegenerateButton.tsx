import { RefreshCw } from "lucide-react";

import styles from "./messages.module.css";

export function RegenerateButton({ busy, onClick }: { busy: boolean; onClick: () => void | Promise<void> }) {
  return <button className={styles.regenerateButton} disabled={busy} onClick={() => { void onClick(); }} type="button">
    <RefreshCw aria-hidden="true" size={14} /> {busy ? "Regenerating…" : "Regenerate"}
  </button>;
}
