import { Sparkles } from "lucide-react";

import { SafeMarkdown } from "./SafeMarkdown";
import styles from "./messages.module.css";

interface TextMessageProps {
  children?: React.ReactNode;
  role: "assistant" | "user";
  label?: string;
  markdown?: string;
}

export function TextMessage({ children, role, label, markdown }: TextMessageProps) {
  if (role === "user") {
    return <div className={styles.userMessage}>{children}</div>;
  }

  return (
    <article className={styles.assistantMessage}>
      <div aria-hidden="true" className={styles.avatar}><Sparkles size={15} /></div>
      <div className={styles.assistantBody}>
        {label === undefined ? null : <p className={styles.messageLabel}>{label}</p>}
        <div className={styles.prose}>{markdown === undefined ? children : <SafeMarkdown>{markdown}</SafeMarkdown>}</div>
      </div>
    </article>
  );
}
