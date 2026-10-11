import { ArrowRight, Check } from "lucide-react";

import type { components } from "../api/generated-types";
import styles from "./messages.module.css";

type QuestionnaireContent = components["schemas"]["QuestionnaireContent"];

export function QuestionnaireMessage({ content }: { content: QuestionnaireContent }) {
  const { tax_intake: intake } = content;
  const question = intake.questions.find((item) => item.order === intake.current_step) ?? intake.questions[0];
  if (question === undefined) return null;

  const selected = new Set(
    intake.answers.find((answer) => answer.question_key === question.key)?.selected_options ?? [],
  );

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
      <fieldset className={styles.questionFieldset}>
        <legend>{question.prompt}</legend>
        <p>Select all that apply.</p>
        <div className={styles.options}>
          {question.options.map((option) => {
            const checked = selected.has(option.code);
            return (
              <label className={styles.option} data-selected={checked} key={option.code}>
                <input
                  checked={checked}
                  name={question.key}
                  readOnly
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
      <button className={styles.primaryButton} type="button">
        Continue <ArrowRight aria-hidden="true" size={17} />
      </button>
    </article>
  );
}
