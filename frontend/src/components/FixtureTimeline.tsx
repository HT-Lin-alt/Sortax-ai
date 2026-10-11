import {
  checklistFixture,
  citationsFixture,
  completedQuestionnaireFixture,
  questionnaireFixture,
  taxSummaryFixture,
} from "../test/fixtures/showcase";
import appStyles from "../app/App.module.css";
import { DocumentChecklistMessage } from "./DocumentChecklistMessage";
import { QuestionnaireMessage } from "./QuestionnaireMessage";
import { QuestionList } from "./QuestionList";
import { TaxSummaryMessage } from "./TaxSummaryMessage";
import { TextMessage } from "./TextMessage";
import { ThinkingMessage } from "./ThinkingMessage";

export function FixtureTimeline() {
  return (
    <section aria-label="Conversation preview" className={appStyles.timeline}>
      <div aria-hidden="true" className={appStyles.ambientOne} />
      <div aria-hidden="true" className={appStyles.ambientTwo} />
      <div className={appStyles.dateDivider}><span>Today</span></div>
      <TextMessage label="2025–26 tax organiser" role="assistant">
        <p><strong>Hi, I&apos;m Sortax.</strong> I can help you organise records for employment income, work expenses, residential rental property and Australian bank interest.</p>
        <p>Tell me what you&apos;d like to prepare and I&apos;ll guide you through it.</p>
      </TextMessage>
      <TextMessage role="user">I&apos;d like to work out which documents I need for my tax return.</TextMessage>
      <QuestionnaireMessage content={questionnaireFixture} />
      <QuestionList content={completedQuestionnaireFixture} />
      <ThinkingMessage />
      <DocumentChecklistMessage citations={citationsFixture} content={checklistFixture} />
      <TaxSummaryMessage citations={citationsFixture} content={taxSummaryFixture} />
      <p className={appStyles.serviceState}>Fixture preview</p>
    </section>
  );
}
