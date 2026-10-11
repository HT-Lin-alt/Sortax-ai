import { Menu, Plus } from "lucide-react";
import { useEffect } from "react";

import { getLiveHealth } from "../api/client";
import { ApiError } from "../api/errors";
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
      <header className={styles.header}>
        <button aria-label="Open menu" className={styles.iconButton} type="button">
          <Menu aria-hidden="true" size={22} />
        </button>
        <div>
          <p className={styles.eyebrow}>Tax preparation assistant</p>
          <h1 className={styles.brand}>Sortax</h1>
        </div>
        <button aria-label="Start a new conversation" className={styles.iconButton} type="button">
          <Plus aria-hidden="true" size={22} />
        </button>
      </header>

      <section aria-labelledby="welcome-heading" className={styles.timeline}>
        <article className={styles.welcomeCard}>
          <span aria-hidden="true" className={styles.mark}>S</span>
          <p className={styles.kicker}>2025–26 limited tax service</p>
          <h2 id="welcome-heading">Let&apos;s get your tax records organised.</h2>
          <p>
            Ask a question or begin the guided intake. Sortax will keep official ATO sources
            attached to document guidance.
          </p>
          <div aria-live="polite" className={styles.status} data-status={state.serviceStatus}>
            <span aria-hidden="true" className={styles.statusDot} />
            {serviceLabel(state.serviceStatus)}
          </div>
        </article>
      </section>

      <footer className={styles.composer}>
        <label className={styles.srOnly} htmlFor="message-input">Message Sortax</label>
        <input disabled id="message-input" placeholder="Message Sortax" type="text" />
        <button aria-label="Send message" disabled type="button">Send</button>
      </footer>
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
