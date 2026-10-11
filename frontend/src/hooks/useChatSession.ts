import { useCallback, useEffect, useReducer, useRef } from "react";

import {
  cancelGeneration,
  createConversation,
  getCurrentIdentity,
  issueDevelopmentToken,
  listMessages,
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

  const refreshHistory = useCallback(async (conversationId: string, accessToken: string) => {
    const page = await listMessages(conversationId, { accessToken });
    dispatch({ type: "history/loaded", messages: page.items });
    return page.items;
  }, []);

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
  }, [consume]);

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

  useEffect(() => () => {
    const controller = activeRequestRef.current;
    const accessToken = tokenRef.current;
    const generationId = generationIdRef.current;
    controller?.abort();
    if (generationId !== null && accessToken !== null) {
      void cancelGeneration(generationId, { accessToken });
    }
  }, []);

  return { state, sendMessage, cancel };
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

function safeMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Sortax could not complete the request.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
