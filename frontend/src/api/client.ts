import type { components } from "./generated-types";
import { errorFromResponse } from "./errors";
import { decodeChatEvent, parseSseStream, type ChatStreamEvent } from "./sse";

export type HealthStatus = components["schemas"]["HealthStatus"];
export type CurrentIdentity = components["schemas"]["CurrentIdentity"];
export type Conversation = components["schemas"]["Conversation"];
export type Message = components["schemas"]["Message"];
export type MessagePage = components["schemas"]["MessagePage"];
export type TokenResponse = components["schemas"]["TokenResponse"];

interface RequestOptions {
  readonly signal?: AbortSignal;
}

interface AuthorizedRequestOptions extends RequestOptions {
  readonly accessToken: string;
}

interface StreamOptions extends AuthorizedRequestOptions {
  readonly lastEventId?: string;
  readonly onEvent: (event: ChatStreamEvent) => void | Promise<void>;
}

export async function getLiveHealth(options: RequestOptions = {}): Promise<HealthStatus> {
  return requestJson<HealthStatus>("/health/live", { ...options, method: "GET" });
}

export async function issueDevelopmentToken(
  payload: components["schemas"]["DevelopmentTokenRequest"],
  options: RequestOptions = {},
): Promise<TokenResponse> {
  return requestJson<TokenResponse>("/api/v1/dev/token", { ...options, method: "POST", body: payload });
}

export async function getCurrentIdentity(options: AuthorizedRequestOptions): Promise<CurrentIdentity> {
  return requestJson<CurrentIdentity>("/api/v1/auth/me", { ...options, method: "GET" });
}

export async function createConversation(
  options: AuthorizedRequestOptions,
  title: string | null = null,
): Promise<Conversation> {
  return requestJson<Conversation>("/api/v1/conversations", {
    ...options,
    method: "POST",
    body: { title } satisfies components["schemas"]["CreateConversationRequest"],
  });
}

export async function listMessages(
  conversationId: string,
  options: AuthorizedRequestOptions,
): Promise<MessagePage> {
  return requestJson<MessagePage>(`/api/v1/conversations/${encodeURIComponent(conversationId)}/messages?limit=100`, {
    ...options,
    method: "GET",
  });
}

export async function startConversation(
  conversationId: string,
  clientRequestId: string,
  options: StreamOptions,
): Promise<void> {
  await requestEventStream(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/start`,
    { client_request_id: clientRequestId } satisfies components["schemas"]["StartConversationRequest"],
    options,
  );
}

export async function sendMessage(
  conversationId: string,
  content: string,
  clientMessageId: string,
  options: StreamOptions,
): Promise<void> {
  await requestEventStream(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
    { client_message_id: clientMessageId, content } satisfies components["schemas"]["CreateMessageRequest"],
    options,
  );
}

export async function cancelGeneration(
  generationId: string,
  options: AuthorizedRequestOptions,
): Promise<components["schemas"]["Generation"]> {
  return requestJson<components["schemas"]["Generation"]>(
    `/api/v1/generations/${encodeURIComponent(generationId)}/cancel`,
    { ...options, method: "POST" },
  );
}

interface JsonRequestOptions extends RequestOptions {
  readonly accessToken?: string;
  readonly method: "GET" | "POST";
  readonly body?: unknown;
}

async function requestJson<T>(path: string, options: JsonRequestOptions): Promise<T> {
  const response = await fetch(path, buildRequest(options));
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

async function requestEventStream(path: string, body: unknown, options: StreamOptions): Promise<void> {
  const headers = new Headers({
    Accept: "text/event-stream",
    Authorization: `Bearer ${options.accessToken}`,
    "Content-Type": "application/json",
  });
  if (options.lastEventId !== undefined) headers.set("Last-Event-ID", options.lastEventId);
  const init: RequestInit = { method: "POST", headers, body: JSON.stringify(body) };
  if (options.signal !== undefined) init.signal = options.signal;
  const response = await fetch(path, init);
  if (!response.ok) throw await errorFromResponse(response);
  if (response.body === null) throw new Error("The service returned an empty event stream.");

  const seenEventIds = new Set<string>();
  const highestSequence = new Map<string, number>();
  await parseSseStream(response.body, async (rawEvent) => {
    if (rawEvent.id !== null && seenEventIds.has(rawEvent.id)) return;
    if (rawEvent.id !== null) seenEventIds.add(rawEvent.id);
    const event = decodeChatEvent(rawEvent);
    if (event.type === "message.delta") {
      const previous = highestSequence.get(event.data.message_id) ?? 0;
      if (event.data.seq <= previous) return;
      highestSequence.set(event.data.message_id, event.data.seq);
    }
    await options.onEvent(event);
  }, options.signal);
}

function buildRequest(options: JsonRequestOptions): RequestInit {
  const headers = new Headers({ Accept: "application/json" });
  if (options.accessToken !== undefined) headers.set("Authorization", `Bearer ${options.accessToken}`);
  const init: RequestInit = { method: options.method, headers };
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(options.body);
  }
  if (options.signal !== undefined) init.signal = options.signal;
  return init;
}
