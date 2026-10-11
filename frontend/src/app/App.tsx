import { useEffect } from "react";

import { getLiveHealth } from "../api/client";
import { ApiError } from "../api/errors";
import { ChatHeader } from "../components/ChatHeader";
import { Composer } from "../components/Composer";
import { FixtureTimeline } from "../components/FixtureTimeline";
import { MessageRenderer } from "../components/MessageRenderer";
import { TextMessage } from "../components/TextMessage";
import { ThinkingMessage } from "../components/ThinkingMessage";
import { useAutoScroll } from "../hooks/useAutoScroll";
import { useChatSession } from "../hooks/useChatSession";
import { useApp } from "./app-context";
import styles from "./App.module.css";

export function App() {
  const fixtureMode = new URLSearchParams(window.location.search).get("fixtures") === "1";
  return fixtureMode ? <FixtureApp /> : <LiveApp />;
}

function FixtureApp() {
  return (
    <main className={styles.shell}>
      <ChatHeader serviceStatus="available" />
      <FixtureTimeline />
      <Composer disabled />
    </main>
  );
}

function LiveApp() {
  const { state: appState, dispatch } = useApp();
  const { state: chatState, sendMessage, cancel, saveIntakeAnswer, finishIntake } = useChatSession();
  const isStreaming = ["starting", "generating", "retrieving"].includes(chatState.streamStatus);
  const timelineRef = useAutoScroll(`${String(chatState.messages.length)}:${String(chatState.streamedText.length)}:${chatState.streamStatus}`);

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: "health/check-started" });
    void getLiveHealth({ signal: controller.signal })
      .then(() => { dispatch({ type: "health/check-succeeded" }); })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          dispatch({ type: "health/check-failed", requestId: error instanceof ApiError ? error.requestId : null });
        }
      });
    return () => { controller.abort(); };
  }, [dispatch]);

  return (
    <main className={styles.shell}>
      <ChatHeader serviceStatus={appState.serviceStatus} />
      <section aria-label="Conversation" className={styles.timeline} ref={timelineRef}>
        <div aria-hidden="true" className={styles.ambientOne} />
        <div aria-hidden="true" className={styles.ambientTwo} />
        <div className={styles.dateDivider}><span>Today</span></div>

        {chatState.phase === "booting" ? (
          <div className={styles.connectionState}><span /><p><strong>Connecting to Sortax</strong>Preparing your conversation…</p></div>
        ) : null}

        {chatState.messages.map((message) => (
          <MessageRenderer
            intake={chatState.taxIntake}
            intakeBusy={["loading", "saving", "completing"].includes(chatState.intakeStatus)}
            intakeError={chatState.intakeError}
            key={message.id}
            message={message}
            onCompleteIntake={finishIntake}
            onSaveAnswer={saveIntakeAnswer}
          />
        ))}

        {chatState.streamedText !== "" ? (
          <TextMessage role="assistant"><p>{chatState.streamedText}</p></TextMessage>
        ) : null}

        {isStreaming && chatState.streamedText === "" ? <ThinkingMessage /> : null}

        {chatState.error !== null ? (
          <div className={styles.errorState} role="alert"><strong>Something went wrong</strong><p>{chatState.error}</p></div>
        ) : null}
      </section>
      <Composer
        disabled={chatState.phase !== "ready"}
        onCancel={cancel}
        onSend={sendMessage}
        streaming={isStreaming}
      />
    </main>
  );
}
