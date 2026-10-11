import { afterEach, describe, expect, it, vi } from "vitest";

import { getCurrentIdentity, getLiveHealth } from "./client";
import { ApiError } from "./errors";
import {
  healthFixture,
  identityFixture,
  unauthorizedFixture,
} from "../test/fixtures/contract";

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
});
