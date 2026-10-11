import type { Message, TaxIntake } from "../api/client";
import type { components } from "../api/generated-types";
import { DocumentChecklistMessage } from "./DocumentChecklistMessage";
import { QuestionnaireMessage } from "./QuestionnaireMessage";
import { QuestionList } from "./QuestionList";
import { TaxSummaryMessage } from "./TaxSummaryMessage";
import { TextMessage } from "./TextMessage";
import styles from "./messages.module.css";

interface MessageRendererProps {
  readonly intake: TaxIntake | null;
  readonly intakeBusy: boolean;
  readonly intakeError: string | null;
  readonly message: Message;
  readonly onCompleteIntake: (intake: TaxIntake) => void | Promise<void>;
  readonly onSaveAnswer: (questionKey: string, selectedOptions: readonly string[]) => Promise<TaxIntake | null>;
}

export function MessageRenderer({
  message,
  intake,
  intakeBusy,
  intakeError,
  onCompleteIntake,
  onSaveAnswer,
}: MessageRendererProps) {
  if (message.role === "user") return <TextMessage role="user">{message.content}</TextMessage>;
  const structured = message.structured_content;
  if (structured !== null) {
    switch (structured.type) {
      case "questionnaire":
        if (intake !== null && intake.id === structured.tax_intake.id) {
          const restoredContent = { type: "questionnaire" as const, tax_intake: intake };
          return intake.status === "questionnaire_active"
            ? <QuestionnaireMessage busy={intakeBusy} content={restoredContent} error={intakeError} intake={intake} onComplete={onCompleteIntake} onSave={onSaveAnswer} />
            : <QuestionList content={restoredContent} />;
        }
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
