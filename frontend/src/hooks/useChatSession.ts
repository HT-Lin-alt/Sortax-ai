import { useCallback, useEffect, useReducer, useRef } from "react";

import {
  cancelGeneration,
  completeTaxIntake,
  decideTaxSummary,
  createConversation,
  getCurrentIdentity,
  getTaxIntake,
  issueDevelopmentToken,
  listMessages,
  putTaxIntakeAnswer,
  retryMessage,
  sendMessage as streamMessage,
  startConversation,
  type Message,
} from "../api/client";
import { ApiError } from "../api/errors";
import type { ChatStreamEvent } from "../api/sse";
import { chatReducer, initialChatState } from "../features/chat/chat-reducer";

const recentConversationKey = "sortax.recentConversationId";
const developmentIdentity = {
  user_id: "11111111-1111-4111-8111-111111111111",
  tenant_id: "22222222-2222-4222-8222-222222222222",
} as const;

export function useChatSession() {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const tokenRef = useRef<string | null>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
  const generationIdRef = useRef<string | null>(null);
  const initializedRef = useRef(false);
  const answerRequestRef = useRef(false);

  const restoreIntake = useCallback(async (messages: readonly Message[], accessToken: string) => {
    const intakeId = findLatestIntakeId(messages);
    if (intakeId === null) return null;
    dispatch({ type: "intake/loading" });
    try {
      const intake = await getTaxIntake(intakeId, { accessToken });
      dispatch({ type: "intake/loaded", intake });
      return intake;
    } catch (error: unknown) {
      dispatch({ type: "intake/failed", message: safeMessage(error) });
      return null;
    }
  }, []);

  const refreshHistory = useCallback(async (conversationId: string, accessToken: string) => {
    const page = await listMessages(conversationId, { accessToken });
    dispatch({ type: "history/loaded", messages: page.items });
    await restoreIntake(page.items, accessToken);
    return page.items;
  }, [restoreIntake]);

  const consume = useCallback(async (
    operation: (onEvent: (event: ChatStreamEvent) => void, signal: AbortSignal) => Promise<void>,
    conversationId: string,
    accessToken: string,
  ) => {
    if (activeRequestRef.current !== null) return;
    const controller = new AbortController();
    activeRequestRef.current = controller;
    dispatch({ type: "stream/requested" });
    const outcome: { terminal: "completed" | "failed" | null } = { terminal: null };
    try {
      await operation((event) => {
        switch (event.type) {
          case "generation.started":
            generationIdRef.current = event.data.generation_id;
            dispatch({ type: "stream/started", generationId: event.data.generation_id });
            break;
          case "retrieval.started":
            dispatch({ type: "stream/retrieving" });
            break;
          case "message.delta":
            dispatch({ type: "stream/delta", delta: event.data.delta });
            break;
          case "message.completed":
            outcome.terminal = "completed";
            break;
          case "message.failed":
            outcome.terminal = "failed";
            generationIdRef.current = null;
            dispatch({ type: "stream/failed", message: event.data.error.message });
            break;
          case "retrieval.completed":
          case "heartbeat":
          case "unknown":
            break;
          default:
            event satisfies never;
        }
      }, controller.signal);
      if (outcome.terminal === null) throw new Error("The response stream ended before completion.");
      await refreshHistory(conversationId, accessToken);
      if (outcome.terminal === "completed") {
        generationIdRef.current = null;
        dispatch({ type: "stream/completed" });
      }
      return outcome.terminal;
    } catch (error: unknown) {
      if (isAbortError(error)) {
        dispatch({ type: "stream/cancelled" });
      } else {
        dispatch({ type: "stream/failed", message: safeMessage(error) });
      }
      try { await refreshHistory(conversationId, accessToken); } catch { /* Preserve the primary stream error. */ }
      return isAbortError(error) ? "cancelled" : "interrupted";
    } finally {
      activeRequestRef.current = null;
    }
  }, [refreshHistory]);

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    void (async () => {
      try {
        const token = await acquireAccessToken();
        tokenRef.current = token;
        await getCurrentIdentity({ accessToken: token });

        let conversationId = readRecentConversationId();
        let messages: readonly Message[] = [];
        if (conversationId !== null) {
          try {
            messages = (await listMessages(conversationId, { accessToken: token })).items;
          } catch (error: unknown) {
            if (!(error instanceof ApiError) || error.status !== 404) throw error;
            conversationId = null;
          }
        }
        if (conversationId === null) {
          const conversation = await createConversation({ accessToken: token }, "Tax organiser");
          conversationId = conversation.id;
          writeRecentConversationId(conversationId);
        }
        dispatch({ type: "bootstrap/succeeded", conversationId, messages });
        if (messages.length > 0) await restoreIntake(messages, token);

        if (messages.length === 0) {
          const requestKey = `sortax.startRequest.${conversationId}`;
          const requestId = localStorage.getItem(requestKey) ?? crypto.randomUUID();
          localStorage.setItem(requestKey, requestId);
          const outcome = await consume(
            (onEvent, signal) => startConversation(conversationId, requestId, { accessToken: token, onEvent, signal }),
            conversationId,
            token,
          );
          if (outcome === "completed" || outcome === "failed") localStorage.removeItem(requestKey);
        }
      } catch (error: unknown) {
        dispatch({ type: "bootstrap/failed", message: safeMessage(error) });
      }
    })();
  }, [consume, restoreIntake]);

  const sendMessage = useCallback(async (content: string) => {
    const trimmed = content.trim();
    const accessToken = tokenRef.current;
    const conversationId = state.conversationId;
    if (trimmed === "" || accessToken === null || conversationId === null || activeRequestRef.current !== null) return;
    const clientMessageId = crypto.randomUUID();
    dispatch({ type: "message/optimistic", message: optimisticMessage(clientMessageId, conversationId, trimmed) });
    await consume(
      (onEvent, signal) => streamMessage(conversationId, trimmed, clientMessageId, { accessToken, onEvent, signal }),
      conversationId,
      accessToken,
    );
  }, [consume, state.conversationId]);

  const cancel = useCallback(async () => {
    const controller = activeRequestRef.current;
    if (controller === null) return;
    const accessToken = tokenRef.current;
    controller.abort();
    const generationId = generationIdRef.current;
    generationIdRef.current = null;
    if (generationId !== null && accessToken !== null) {
      try { await cancelGeneration(generationId, { accessToken }); } catch { /* Local abort still takes precedence. */ }
    }
  }, []);

  const saveIntakeAnswer = useCallback(async (questionKey: string, selectedOptions: readonly string[]) => {
    const intake = state.taxIntake;
    const accessToken = tokenRef.current;
    if (intake === null || accessToken === null || answerRequestRef.current) return null;
    answerRequestRef.current = true;
    dispatch({ type: "intake/saving" });
    try {
      const updated = await putTaxIntakeAnswer(
        intake.id,
        questionKey,
        selectedOptions,
        intake.version,
        { accessToken },
      );
      dispatch({ type: "intake/loaded", intake: updated });
      return updated;
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        const restored = await getTaxIntake(intake.id, { accessToken });
        dispatch({ type: "intake/loaded", intake: restored });
        return restored;
      }
      dispatch({ type: "intake/failed", message: safeMessage(error) });
      return null;
    } finally {
      answerRequestRef.current = false;
    }
  }, [state.taxIntake]);

  const finishIntake = useCallback(async (updatedIntake = state.taxIntake) => {
    const accessToken = tokenRef.current;
    const conversationId = state.conversationId;
    if (updatedIntake === null || accessToken === null || conversationId === null || activeRequestRef.current !== null) return;
    dispatch({ type: "intake/completing" });
    const requestKey = `sortax.completeRequest.${updatedIntake.id}`;
    const requestId = readLocalValue(requestKey) ?? crypto.randomUUID();
    writeLocalValue(requestKey, requestId);
    const outcome = await consume(
      (onEvent, signal) => completeTaxIntake(updatedIntake.id, requestId, updatedIntake.version, { accessToken, onEvent, signal }),
      conversationId,
      accessToken,
    );
    if (outcome === "completed" || outcome === "failed") removeLocalValue(requestKey);
    if (outcome === "interrupted") {
      dispatch({ type: "intake/failed", message: "The checklist stream was interrupted. Your saved answers are safe." });
    }
  }, [consume, state.conversationId, state.taxIntake]);

  const decideSummary = useCallback(async (intakeId: string, requested: boolean) => {
    const accessToken = tokenRef.current;
    const conversationId = state.conversationId;
    const intake = state.taxIntake;
    if (accessToken === null || conversationId === null || intake?.id !== intakeId || activeRequestRef.current !== null) return;
    const requestKey = `sortax.summaryRequest.${intakeId}`;
    const requestId = readLocalValue(requestKey) ?? crypto.randomUUID();
    writeLocalValue(requestKey, requestId);
    const outcome = await consume((onEvent, signal) => decideTaxSummary(intakeId, requestId, requested, intake.version, { accessToken, onEvent, signal }), conversationId, accessToken);
    if (outcome === "completed" || outcome === "failed") removeLocalValue(requestKey);
  }, [consume, state.conversationId, state.taxIntake]);

  const regenerate = useCallback(async (messageId: string) => {
    const accessToken = tokenRef.current;
    const conversationId = state.conversationId;
    if (accessToken === null || conversationId === null || activeRequestRef.current !== null) return;
    const controller = new AbortController();
    activeRequestRef.current = controller;
    dispatch({ type: "stream/requested" });
    try {
      const generation = await retryMessage(messageId, crypto.randomUUID(), { accessToken });
      generationIdRef.current = generation.id;
      dispatch({ type: "stream/started", generationId: generation.id });
      await refreshHistory(conversationId, accessToken);
      dispatch({ type: "stream/completed" });
    } catch (error: unknown) {
      dispatch({ type: "stream/failed", message: safeMessage(error) });
      try { await refreshHistory(conversationId, accessToken); } catch { /* Preserve the retry error. */ }
    } finally {
      activeRequestRef.current = null;
    }
  }, [refreshHistory, state.conversationId]);

  useEffect(() => () => {
    const controller = activeRequestRef.current;
    const accessToken = tokenRef.current;
    const generationId = generationIdRef.current;
    controller?.abort();
    if (generationId !== null && accessToken !== null) {
      void cancelGeneration(generationId, { accessToken });
    }
  }, []);

  return { state, sendMessage, cancel, saveIntakeAnswer, finishIntake, decideSummary, regenerate };
}

async function acquireAccessToken(): Promise<string> {
  const configured = import.meta.env.VITE_ACCESS_TOKEN;
  if (typeof configured === "string" && configured !== "") return configured;
  if (!(import.meta.env.DEV || import.meta.env.MODE === "test")) {
    throw new Error("No production access token is configured.");
  }
  return (await issueDevelopmentToken(developmentIdentity)).access_token;
}

function optimisticMessage(id: string, conversationId: string, content: string): Message {
  const now = new Date().toISOString();
  return {
    id,
    conversation_id: conversationId,
    role: "user",
    content,
    content_type: "text",
    structured_content: null,
    status: "completed",
    grounded: false,
    citation_count: 0,
    citations: [],
    created_at: now,
    completed_at: now,
  };
}

function readRecentConversationId(): string | null {
  try { return localStorage.getItem(recentConversationKey); } catch { return null; }
}

function writeRecentConversationId(value: string): void {
  try { localStorage.setItem(recentConversationKey, value); } catch { /* Recovery remains available in server history. */ }
}

function findLatestIntakeId(messages: readonly Message[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const structured = messages[index]?.structured_content;
    if (structured === null || structured === undefined) continue;
    return structured.type === "questionnaire" ? structured.tax_intake.id : structured.tax_intake_id;
  }
  return null;
}

function readLocalValue(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function writeLocalValue(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* Idempotency still applies during this page lifetime. */ }
}

function removeLocalValue(key: string): void {
  try { localStorage.removeItem(key); } catch { /* Expiry makes an orphaned request key harmless. */ }
}

function safeMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Sortax could not complete the request.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
