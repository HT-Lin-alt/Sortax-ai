import { ArrowRight, Check, LoaderCircle } from "lucide-react";
import { type SubmitEvent, useState } from "react";

import type { TaxIntake } from "../api/client";
import type { components } from "../api/generated-types";
import styles from "./messages.module.css";

type QuestionnaireContent = components["schemas"]["QuestionnaireContent"];

interface QuestionnaireMessageProps {
  readonly content: QuestionnaireContent;
  readonly intake?: TaxIntake;
  readonly busy?: boolean;
  readonly error?: string | null;
  readonly onComplete?: (intake: TaxIntake) => void | Promise<void>;
  readonly onSave?: (questionKey: string, selectedOptions: readonly string[]) => Promise<TaxIntake | null>;
}

export function QuestionnaireMessage({
  content,
  intake: restoredIntake,
  busy = false,
  error = null,
  onComplete,
  onSave,
}: QuestionnaireMessageProps) {
  const intake = restoredIntake ?? content.tax_intake;
  const question = intake.questions.find((item) => item.order === intake.current_step)
    ?? intake.questions[intake.current_step]
    ?? intake.questions[0];
  if (question === undefined) return null;
  const savedSelection = intake.answers.find((answer) => answer.question_key === question.key)?.selected_options ?? [];
  return (
    <QuestionnaireStep
      busy={busy}
      error={error}
      intake={intake}
      key={`${intake.id}:${question.key}:${String(intake.version)}`}
      onComplete={onComplete}
      onSave={onSave}
      question={question}
      savedSelection={savedSelection}
    />
  );
}

interface QuestionnaireStepProps {
  readonly busy: boolean;
  readonly error: string | null;
  readonly intake: TaxIntake;
  readonly onComplete: ((intake: TaxIntake) => void | Promise<void>) | undefined;
  readonly onSave: ((questionKey: string, selectedOptions: readonly string[]) => Promise<TaxIntake | null>) | undefined;
  readonly question: components["schemas"]["TaxQuestion"];
  readonly savedSelection: readonly string[];
}

function QuestionnaireStep({ busy, error, intake, onComplete, onSave, question, savedSelection }: QuestionnaireStepProps) {
  const [selected, setSelected] = useState<readonly string[]>(savedSelection);

  const choose = (code: string, checked: boolean) => {
    if (question.question_type === "single") {
      setSelected(checked ? [code] : []);
      return;
    }
    if (code === "none" && checked) {
      setSelected([code]);
      return;
    }
    setSelected((current) => {
      const withoutNone = current.filter((item) => item !== "none" && item !== code);
      return checked ? [...withoutNone, code] : withoutNone;
    });
  };

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (onSave === undefined || selected.length === 0 || busy) return;
    const updated = await onSave(question.key, selected);
    const persisted = updated?.answers.find((answer) => answer.question_key === question.key)?.selected_options;
    const answerWasSaved = persisted?.length === selected.length
      && selected.every((option) => persisted.includes(option));
    if (updated !== null && answerWasSaved && question.order === intake.questions.length && onComplete !== undefined) {
      await onComplete(updated);
    }
  };

  const isLast = question.order === intake.questions.length;
  return (
    <article className={styles.featureCard} data-testid="questionnaire-card">
      <header className={styles.cardHeader}>
        <div>
          <p className={styles.eyebrow}>Guided tax check</p>
          <h2>A few details first</h2>
        </div>
        <span className={styles.stepCount}>{question.order} of {intake.questions.length}</span>
      </header>
      <div aria-label={`Step ${String(question.order)} of ${String(intake.questions.length)}`} className={styles.progress} role="progressbar" aria-valuemin={1} aria-valuemax={intake.questions.length} aria-valuenow={question.order}>
        {intake.questions.map((item) => (
          <span className={item.order <= question.order ? styles.progressActive : undefined} key={item.key} />
        ))}
      </div>
      <form onSubmit={(event) => { void submit(event); }}>
        <fieldset aria-describedby={error === null ? undefined : `${question.key}-error`} className={styles.questionFieldset} disabled={busy}>
          <legend>{question.prompt}</legend>
          <p>{question.question_type === "single" ? "Choose one answer." : "Select all that apply."}</p>
          <div className={styles.options}>
            {question.options.map((option) => {
              const checked = selected.includes(option.code);
              return (
                <label className={styles.option} data-selected={checked} key={option.code}>
                  <input
                    checked={checked}
                    name={question.key}
                    onChange={(event) => { choose(option.code, event.target.checked); }}
                    type={question.question_type === "single" ? "radio" : "checkbox"}
                    value={option.code}
                  />
                  <span aria-hidden="true" className={styles.optionControl}>{checked ? <Check size={14} /> : null}</span>
                  <span>{option.label}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
        {error === null ? null : <p className={styles.inlineError} id={`${question.key}-error`} role="alert">{error}</p>}
        <button className={styles.primaryButton} disabled={busy || selected.length === 0} type="submit">
          {busy ? <><LoaderCircle aria-hidden="true" className={styles.spinner} size={17} /> Saving…</> : <>{isLast ? "Find my documents" : "Continue"} <ArrowRight aria-hidden="true" size={17} /></>}
        </button>
      </form>
    </article>
  );
}
