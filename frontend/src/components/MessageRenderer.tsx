import type { Message } from "../api/client";
import type { components } from "../api/generated-types";
import { DocumentChecklistMessage } from "./DocumentChecklistMessage";
import { QuestionnaireMessage } from "./QuestionnaireMessage";
import { TaxSummaryMessage } from "./TaxSummaryMessage";
import { TextMessage } from "./TextMessage";
import styles from "./messages.module.css";

export function MessageRenderer({ message }: { message: Message }) {
  if (message.role === "user") return <TextMessage role="user">{message.content}</TextMessage>;
  const structured = message.structured_content;
  if (structured !== null) {
    switch (structured.type) {
      case "questionnaire":
        return <QuestionnaireMessage content={structured} />;
      case "document_checklist":
        return <DocumentChecklistMessage citations={message.citations} content={structured} />;
      case "summary_confirmation":
        return <SummaryConfirmation content={structured} />;
      case "tax_summary":
        return <TaxSummaryMessage citations={message.citations} content={structured} />;
      default:
        structured satisfies never;
    }
  }
  return <TextMessage role="assistant"><p>{message.content}</p></TextMessage>;
}

function SummaryConfirmation({ content }: { content: components["schemas"]["SummaryConfirmationContent"] }) {
  return (
    <article className={styles.featureCard}>
      <p className={styles.eyebrow}>Optional summary</p>
      <h2 className={styles.standalonePrompt}>{content.prompt}</h2>
      <div className={styles.confirmationActions}>
        <button type="button">No, thanks</button>
        <button type="button">Yes, create summary</button>
      </div>
    </article>
  );
}
