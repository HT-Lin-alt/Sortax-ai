import { useEffect } from "react";

import { getLiveHealth } from "../api/client";
import { ApiError } from "../api/errors";
import { ChatHeader } from "../components/ChatHeader";
import { Composer } from "../components/Composer";
import { DocumentChecklistMessage } from "../components/DocumentChecklistMessage";
import { QuestionnaireMessage } from "../components/QuestionnaireMessage";
import { QuestionList } from "../components/QuestionList";
import { TaxSummaryMessage } from "../components/TaxSummaryMessage";
import { TextMessage } from "../components/TextMessage";
import { ThinkingMessage } from "../components/ThinkingMessage";
import {
  checklistFixture,
  citationsFixture,
  completedQuestionnaireFixture,
  questionnaireFixture,
  taxSummaryFixture,
} from "../test/fixtures/showcase";
import { useApp } from "./app-context";
import styles from "./App.module.css";

export function App() {
  const { state, dispatch } = useApp();

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: "health/check-started" });
    void getLiveHealth({ signal: controller.signal })
      .then(() => {
        dispatch({ type: "health/check-succeeded" });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          dispatch({
            type: "health/check-failed",
            requestId: error instanceof ApiError ? error.requestId : null,
          });
        }
      });
    return () => {
      controller.abort();
    };
  }, [dispatch]);

  return (
    <main className={styles.shell}>
      <ChatHeader serviceStatus={state.serviceStatus} />

      <section aria-label="Conversation preview" className={styles.timeline}>
        <div aria-hidden="true" className={styles.ambientOne} />
        <div aria-hidden="true" className={styles.ambientTwo} />
        <div className={styles.dateDivider}><span>Today</span></div>

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

        <p aria-live="polite" className={styles.serviceState}>{serviceLabel(state.serviceStatus)}</p>
      </section>

      <Composer />
    </main>
  );
}

function serviceLabel(status: "checking" | "available" | "unavailable"): string {
  switch (status) {
    case "checking":
      return "Checking service…";
    case "available":
      return "Service available";
    case "unavailable":
      return "Service unavailable";
  }
}
