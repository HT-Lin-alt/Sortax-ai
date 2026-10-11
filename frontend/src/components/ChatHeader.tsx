import { Menu, MessageSquarePlus, Sparkles } from "lucide-react";

import styles from "./chrome.module.css";

interface ChatHeaderProps {
  serviceStatus: "checking" | "available" | "unavailable";
}

export function ChatHeader({ serviceStatus }: ChatHeaderProps) {
  return (
    <header className={styles.header}>
      <button aria-label="Open menu" className={styles.iconButton} type="button">
        <Menu aria-hidden="true" size={21} strokeWidth={1.8} />
      </button>
      <div className={styles.identity}>
        <span aria-hidden="true" className={styles.brandMark}>
          <Sparkles size={15} strokeWidth={2.2} />
        </span>
        <div>
          <h1>Sortax</h1>
          <p><span className={styles.statusDot} data-status={serviceStatus} />ATO-guided workspace</p>
        </div>
      </div>
      <button aria-label="Start a new conversation" className={styles.iconButton} type="button">
        <MessageSquarePlus aria-hidden="true" size={20} strokeWidth={1.8} />
      </button>
    </header>
  );
}
