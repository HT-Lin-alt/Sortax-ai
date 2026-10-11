import { describe, expect, it } from "vitest";

import { chatReducer, initialChatState } from "./chat-reducer";

describe("chatReducer", () => {
  it("accumulates streamed deltas and clears them on completion", () => {
    const started = chatReducer(initialChatState, { type: "stream/started", generationId: "generation-1" });
    const first = chatReducer(started, { type: "stream/delta", delta: "Hello" });
    const second = chatReducer(first, { type: "stream/delta", delta: " there" });

    expect(second).toMatchObject({ streamStatus: "generating", streamedText: "Hello there" });
    expect(chatReducer(second, { type: "stream/completed" })).toMatchObject({
      streamStatus: "idle",
      generationId: null,
      streamedText: "",
    });
  });

  it("records a stable failure without discarding history", () => {
    const state = { ...initialChatState, messages: [] };
    expect(chatReducer(state, { type: "stream/failed", message: "Provider unavailable" })).toMatchObject({
      messages: [],
      streamStatus: "failed",
      error: "Provider unavailable",
    });
  });
});
