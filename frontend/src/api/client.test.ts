import { afterEach, describe, expect, it, vi } from "vitest";

import { getCurrentIdentity, getLiveHealth, putTaxIntakeAnswer, sendMessage } from "./client";
import { ApiError } from "./errors";
import {
  healthFixture,
  identityFixture,
  unauthorizedFixture,
} from "../test/fixtures/contract";
import { questionnaireFixture } from "../test/fixtures/showcase";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API client", () => {
  it("calls the live health endpoint", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(healthFixture), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getLiveHealth()).resolves.toEqual(healthFixture);
    expect(fetchMock).toHaveBeenCalledWith(
      "/health/live",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("adds a bearer token only to an authorized request", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify(identityFixture),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getCurrentIdentity({ accessToken: "development-token" });
    const requestInit = fetchMock.mock.calls[0]?.[1];
    const headers = new Headers(requestInit?.headers);
    expect(headers.get("Authorization")).toBe("Bearer development-token");
  });

  it("normalizes an API error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify(unauthorizedFixture),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const error = await getCurrentIdentity({ accessToken: "expired" }).catch(
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "unauthorized", requestId: "request-123" });
  });

  it("streams POST events and removes duplicate IDs and delta sequences", async () => {
    const body = [
      sse("generation.started", "1", { generation_id: "generation-1", message_id: "message-1" }),
      sse("message.delta", "2", { generation_id: "generation-1", message_id: "message-1", seq: 1, delta: "Hello" }),
      sse("message.delta", "2", { generation_id: "generation-1", message_id: "message-1", seq: 1, delta: "Hello" }),
      sse("message.delta", "3", { generation_id: "generation-1", message_id: "message-1", seq: 1, delta: " ignored" }),
      sse("message.delta", "4", { generation_id: "generation-1", message_id: "message-1", seq: 2, delta: " world" }),
      sse("message.completed", "5", {
        generation_id: "generation-1",
        message_id: "message-1",
        content_type: "text",
        structured_content: null,
        completion_kind: "general_chat",
        grounded: false,
        citations: [],
      }),
    ].join("");
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const events: string[] = [];

    await sendMessage("conversation-1", "Hi", "client-1", {
      accessToken: "token",
      onEvent: (event) => { events.push(event.type === "message.delta" ? event.data.delta : event.type); },
    });

    expect(events).toEqual(["generation.started", "Hello", " world", "message.completed"]);
    const [path, init] = fetchMock.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/conversations/conversation-1/messages");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token");
  });

  it("sends the current intake version with a replacement answer", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(questionnaireFixture.tax_intake), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await putTaxIntakeAnswer("intake-1", "work_expenses", ["working_from_home"], 3, { accessToken: "token" });

    const [path, init] = fetchMock.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/tax-intakes/intake-1/answers/work_expenses");
    expect(init?.method).toBe("PUT");
    const requestBody = init?.body;
    if (typeof requestBody !== "string") throw new Error("Expected a JSON request body");
    expect(JSON.parse(requestBody)).toEqual({ selected_options: ["working_from_home"], version: 3 });
  });
});

function sse(event: string, id: string, data: unknown): string {
  return `event: ${event}\nid: ${id}\ndata: ${JSON.stringify(data)}\n\n`;
}
