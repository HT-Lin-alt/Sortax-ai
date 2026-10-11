import { Check } from "lucide-react";

import type { components } from "../api/generated-types";
import styles from "./messages.module.css";

type QuestionnaireContent = components["schemas"]["QuestionnaireContent"];

export function QuestionList({ content }: { content: QuestionnaireContent }) {
  const { tax_intake: intake } = content;
  const answerMap = new Map(intake.answers.map((answer) => [answer.question_key, answer.selected_options]));

  return (
    <article className={styles.completedCard}>
      <header>
        <span aria-hidden="true"><Check size={17} /></span>
        <div><p className={styles.eyebrow}>Details saved</p><h2>Your answers</h2></div>
      </header>
      <ol className={styles.answerList}>
        {intake.questions.map((question) => {
          const selected = new Set(answerMap.get(question.key) ?? []);
          const labels = question.options.filter((option) => selected.has(option.code)).map((option) => option.label);
          return (
            <li key={question.key}>
              <span>{question.order}</span>
              <div><p>{question.prompt}</p><strong>{labels.join(", ") || "Not answered"}</strong></div>
            </li>
          );
        })}
      </ol>
    </article>
  );
}
