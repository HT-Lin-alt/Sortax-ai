import type { Message, TaxIntake } from "../../api/client";

export type ChatPhase = "booting" | "ready" | "error";
export type StreamStatus = "idle" | "starting" | "generating" | "retrieving" | "failed" | "cancelled";

export interface ChatState {
  readonly phase: ChatPhase;
  readonly conversationId: string | null;
  readonly messages: readonly Message[];
  readonly streamStatus: StreamStatus;
  readonly generationId: string | null;
  readonly streamedText: string;
  readonly error: string | null;
  readonly taxIntake: TaxIntake | null;
  readonly intakeStatus: "idle" | "loading" | "saving" | "completing" | "error";
  readonly intakeError: string | null;
}

export type ChatAction =
  | { readonly type: "bootstrap/succeeded"; readonly conversationId: string; readonly messages: readonly Message[] }
  | { readonly type: "bootstrap/failed"; readonly message: string }
  | { readonly type: "history/loaded"; readonly messages: readonly Message[] }
  | { readonly type: "message/optimistic"; readonly message: Message }
  | { readonly type: "stream/requested" }
  | { readonly type: "stream/started"; readonly generationId: string }
  | { readonly type: "stream/retrieving" }
  | { readonly type: "stream/delta"; readonly delta: string }
  | { readonly type: "stream/completed" }
  | { readonly type: "stream/failed"; readonly message: string }
  | { readonly type: "stream/cancelled" }
  | { readonly type: "intake/loading" }
  | { readonly type: "intake/saving" }
  | { readonly type: "intake/completing" }
  | { readonly type: "intake/loaded"; readonly intake: TaxIntake }
  | { readonly type: "intake/failed"; readonly message: string };

export const initialChatState: ChatState = {
  phase: "booting",
  conversationId: null,
  messages: [],
  streamStatus: "idle",
  generationId: null,
  streamedText: "",
  error: null,
  taxIntake: null,
  intakeStatus: "idle",
  intakeError: null,
};

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "bootstrap/succeeded":
      return { ...state, phase: "ready", conversationId: action.conversationId, messages: action.messages, error: null };
    case "bootstrap/failed":
      return { ...state, phase: "error", streamStatus: "idle", error: action.message };
    case "history/loaded":
      return { ...state, messages: action.messages };
    case "message/optimistic":
      return { ...state, messages: [...state.messages, action.message] };
    case "stream/requested":
      return { ...state, streamStatus: "starting", generationId: null, streamedText: "", error: null };
    case "stream/started":
      return { ...state, streamStatus: "generating", generationId: action.generationId };
    case "stream/retrieving":
      return { ...state, streamStatus: "retrieving" };
    case "stream/delta":
      return { ...state, streamStatus: "generating", streamedText: state.streamedText + action.delta };
    case "stream/completed":
      return { ...state, streamStatus: "idle", generationId: null, streamedText: "", error: null };
    case "stream/failed":
      return { ...state, streamStatus: "failed", generationId: null, error: action.message };
    case "stream/cancelled":
      return { ...state, streamStatus: "cancelled", generationId: null, streamedText: "" };
    case "intake/loading":
      return { ...state, intakeStatus: "loading", intakeError: null };
    case "intake/saving":
      return { ...state, intakeStatus: "saving", intakeError: null };
    case "intake/completing":
      return { ...state, intakeStatus: "completing", intakeError: null };
    case "intake/loaded":
      return { ...state, taxIntake: action.intake, intakeStatus: "idle", intakeError: null };
    case "intake/failed":
      return { ...state, intakeStatus: "error", intakeError: action.message };
    default:
      return action satisfies never;
  }
}
