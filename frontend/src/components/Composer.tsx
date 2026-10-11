import { ArrowUp, Plus } from "lucide-react";

import styles from "./chrome.module.css";

export function Composer() {
  return (
    <footer className={styles.composer}>
      <div className={styles.composerField}>
        <button aria-label="Add attachment (not available)" className={styles.addButton} disabled type="button">
          <Plus aria-hidden="true" size={20} />
        </button>
        <label className={styles.srOnly} htmlFor="message-input">Message Sortax</label>
        <textarea
          aria-describedby="composer-note"
          disabled
          id="message-input"
          placeholder="Ask Sortax about your records"
          rows={1}
        />
        <button aria-label="Send message" className={styles.sendButton} disabled type="button">
          <ArrowUp aria-hidden="true" size={19} strokeWidth={2.4} />
        </button>
      </div>
      <p id="composer-note">General information only · Check important details with the ATO</p>
    </footer>
  );
}
