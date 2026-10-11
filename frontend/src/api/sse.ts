import type { components } from "./generated-types";

export interface RawSseEvent {
  readonly event: string;
  readonly id: string | null;
  readonly data: string;
}

interface EventWithData<TType extends string, TData> {
  readonly type: TType;
  readonly id: string | null;
  readonly data: TData;
}

export type ChatStreamEvent =
  | EventWithData<"generation.started", components["schemas"]["GenerationStartedEvent"]>
  | EventWithData<"retrieval.started", components["schemas"]["RetrievalStartedEvent"]>
  | EventWithData<"retrieval.completed", components["schemas"]["RetrievalCompletedEvent"]>
  | EventWithData<"message.delta", components["schemas"]["MessageDeltaEvent"]>
  | EventWithData<"message.completed", components["schemas"]["MessageCompletedEvent"]>
  | EventWithData<"message.failed", components["schemas"]["MessageFailedEvent"]>
  | EventWithData<"heartbeat", components["schemas"]["HeartbeatEvent"]>
  | EventWithData<"unknown", unknown> & { readonly eventName: string };

export class SseProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SseProtocolError";
  }
}

export async function parseSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: RawSseEvent) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let eventId: string | null = null;
  let dataLines: string[] = [];

  const dispatch = async () => {
    if (dataLines.length > 0) {
      await onEvent({ event: eventName, id: eventId, data: dataLines.join("\n") });
    }
    eventName = "message";
    dataLines = [];
  };

  const processLine = async (rawLine: string) => {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line === "") {
      await dispatch();
      return;
    }
    if (line.startsWith(":")) return;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const rawValue = colon === -1 ? "" : line.slice(colon + 1);
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
    switch (field) {
      case "event":
        eventName = value;
        break;
      case "id":
        if (!value.includes("\0")) eventId = value;
        break;
      case "data":
        dataLines.push(value);
        break;
      default:
        break;
    }
  };

  try {
    let result = await reader.read();
    while (!result.done) {
      if (signal?.aborted === true) throw abortError();
      buffer += decoder.decode(result.value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        await processLine(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        newline = buffer.indexOf("\n");
      }
      result = await reader.read();
    }
    buffer += decoder.decode();
    if (buffer !== "") await processLine(buffer);
    await dispatch();
  } finally {
    reader.releaseLock();
  }
}

export function decodeChatEvent(event: RawSseEvent): ChatStreamEvent {
  const data: unknown = parseEventData(event.data);
  const base = { id: event.id, data };
  switch (event.event) {
    case "generation.started":
      return { ...base, type: event.event, data: data as components["schemas"]["GenerationStartedEvent"] };
    case "retrieval.started":
      return { ...base, type: event.event, data: data as components["schemas"]["RetrievalStartedEvent"] };
    case "retrieval.completed":
      return { ...base, type: event.event, data: data as components["schemas"]["RetrievalCompletedEvent"] };
    case "message.delta":
      return { ...base, type: event.event, data: data as components["schemas"]["MessageDeltaEvent"] };
    case "message.completed":
      return { ...base, type: event.event, data: data as components["schemas"]["MessageCompletedEvent"] };
    case "message.failed":
      return { ...base, type: event.event, data: data as components["schemas"]["MessageFailedEvent"] };
    case "heartbeat":
      return { ...base, type: event.event, data: data as components["schemas"]["HeartbeatEvent"] };
    default:
      return { ...base, type: "unknown", eventName: event.event };
  }
}

function parseEventData(data: string): unknown {
  try {
    return JSON.parse(data) as unknown;
  } catch {
    throw new SseProtocolError("The service returned malformed stream data.");
  }
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}
