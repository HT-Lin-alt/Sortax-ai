import { describe, expect, it } from "vitest";

import { appReducer, initialAppState } from "./app-reducer";

describe("appReducer", () => {
  it("records a successful health check", () => {
    expect(appReducer(initialAppState, { type: "health/check-succeeded" })).toEqual({
      serviceStatus: "available",
      requestId: null,
    });
  });

  it("keeps only the safe request identifier for failures", () => {
    expect(
      appReducer(initialAppState, {
        type: "health/check-failed",
        requestId: "request-123",
      }),
    ).toEqual({ serviceStatus: "unavailable", requestId: "request-123" });
  });
});
