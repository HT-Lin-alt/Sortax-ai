import type { Message, TaxIntake } from "../api/client";
import { DocumentChecklistMessage } from "./DocumentChecklistMessage";
import { QuestionnaireMessage } from "./QuestionnaireMessage";
import { QuestionList } from "./QuestionList";
import { RegenerateButton } from "./RegenerateButton";
import { SummaryConfirmationMessage } from "./SummaryConfirmationMessage";
import { TaxSummaryMessage } from "./TaxSummaryMessage";
import { TextMessage } from "./TextMessage";

interface MessageRendererProps {
  readonly intake: TaxIntake | null;
  readonly intakeBusy: boolean;
  readonly intakeError: string | null;
  readonly message: Message;
  readonly onCompleteIntake: (intake: TaxIntake) => void | Promise<void>;
  readonly onSaveAnswer: (questionKey: string, selectedOptions: readonly string[]) => Promise<TaxIntake | null>;
  readonly onSummaryDecision?: (intakeId: string, requested: boolean) => void | Promise<void>;
  readonly onRetry?: (messageId: string) => void | Promise<void>;
  readonly retryBusy?: boolean;
  readonly summaryBusy?: boolean;
}

export function MessageRenderer({
  message,
  intake,
  intakeBusy,
  intakeError,
  onCompleteIntake,
  onSaveAnswer,
  onSummaryDecision,
  onRetry,
  retryBusy = false,
  summaryBusy = false,
}: MessageRendererProps) {
  if (message.role === "system") return null;
  if (message.role === "user") return <TextMessage role="user">{message.content}</TextMessage>;
  const canRetry = onRetry !== undefined && message.status === "completed" && (message.completion_kind === "answer" || message.completion_kind === "clarification" || message.completion_kind === "general_chat");
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
        return <SummaryConfirmationMessage busy={summaryBusy} content={structured} onDecision={onSummaryDecision === undefined ? undefined : (requested) => onSummaryDecision(structured.tax_intake_id, requested)} />;
      case "tax_summary":
        return <TaxSummaryMessage citations={message.citations} content={structured} />;
      default:
        structured satisfies never;
    }
  }
  return <><TextMessage markdown={message.content} role="assistant" />{canRetry ? <RegenerateButton busy={retryBusy} onClick={() => onRetry(message.id)} /> : null}</>;
}
