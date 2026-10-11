import { ArrowUp, Plus, Square } from "lucide-react";
import { type KeyboardEvent, type SubmitEvent, useState } from "react";

import styles from "./chrome.module.css";

interface ComposerProps {
  readonly disabled?: boolean;
  readonly streaming?: boolean;
  readonly onCancel?: () => void | Promise<void>;
  readonly onSend?: (message: string) => void | Promise<void>;
}

export function Composer({ disabled = false, streaming = false, onCancel, onSend }: ComposerProps) {
  const [value, setValue] = useState("");

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = value.trim();
    if (message === "" || disabled || streaming || onSend === undefined) return;
    setValue("");
    void onSend(message);
  };

  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <footer className={styles.composer}>
      <form className={styles.composerField} onSubmit={submit}>
        <button aria-label="Add attachment (not available)" className={styles.addButton} disabled type="button">
          <Plus aria-hidden="true" size={20} />
        </button>
        <label className={styles.srOnly} htmlFor="message-input">Message Sortax</label>
        <textarea
          aria-describedby="composer-note"
          disabled={disabled}
          id="message-input"
          onChange={(event) => { setValue(event.target.value); }}
          onKeyDown={keyDown}
          placeholder={disabled ? "Connecting to Sortax…" : "Ask Sortax a question"}
          rows={1}
          value={value}
        />
        {streaming ? (
          <button aria-label="Stop generating" className={styles.sendButton} onClick={() => { void onCancel?.(); }} type="button">
            <Square aria-hidden="true" fill="currentColor" size={13} />
          </button>
        ) : (
          <button aria-label="Send message" className={styles.sendButton} disabled={disabled || value.trim() === ""} type="submit">
            <ArrowUp aria-hidden="true" size={19} strokeWidth={2.4} />
          </button>
        )}
      </form>
      <p id="composer-note">General information only · Check important details with the ATO</p>
    </footer>
  );
}
