import { describe, expect, it } from "vitest";

import { decodeChatEvent, parseSseStream, SseProtocolError, type RawSseEvent } from "./sse";

describe("SSE parser", () => {
  it("parses events split across arbitrary UTF-8 chunks and joins data lines", async () => {
    const payload = 'event: message.delta\r\nid: 7\r\ndata: {"delta":"税\n' +
      'data: 务"}\r\n\r\n';
    const bytes = new TextEncoder().encode(payload);
    const events: RawSseEvent[] = [];

    await parseSseStream(byteStream([
      bytes.slice(0, 17),
      bytes.slice(17, 45),
      bytes.slice(45, 47),
      bytes.slice(47),
    ]), (event) => { events.push(event); });

    expect(events).toEqual([{ event: "message.delta", id: "7", data: '{"delta":"税\n务"}' }]);
  });

  it("ignores comments and preserves unknown events", async () => {
    const events: RawSseEvent[] = [];
    await parseSseStream(byteStream([new TextEncoder().encode(": keepalive\nevent: future.event\ndata: {\"ok\":true}\n\n")]), (event) => { events.push(event); });

    const event = events[0];
    if (event === undefined) throw new Error("Expected an SSE event");
    expect(decodeChatEvent(event)).toMatchObject({ type: "unknown", eventName: "future.event" });
  });

  it("rejects malformed JSON without exposing its body", () => {
    expect(() => decodeChatEvent({ event: "message.delta", id: "1", data: "not-json" })).toThrow(SseProtocolError);
  });
});

function byteStream(chunks: readonly Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}
