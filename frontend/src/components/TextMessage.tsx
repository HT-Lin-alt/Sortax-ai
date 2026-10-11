import { Sparkles } from "lucide-react";

import styles from "./messages.module.css";

interface TextMessageProps {
  children: React.ReactNode;
  role: "assistant" | "user";
  label?: string;
}

export function TextMessage({ children, role, label }: TextMessageProps) {
  if (role === "user") {
    return <div className={styles.userMessage}>{children}</div>;
  }

  return (
    <article className={styles.assistantMessage}>
      <div aria-hidden="true" className={styles.avatar}><Sparkles size={15} /></div>
      <div className={styles.assistantBody}>
        {label === undefined ? null : <p className={styles.messageLabel}>{label}</p>}
        <div className={styles.prose}>{children}</div>
      </div>
    </article>
  );
}
