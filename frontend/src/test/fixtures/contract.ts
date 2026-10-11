import type { components } from "../../api/generated-types";

export const healthFixture = {
  status: "ok",
} satisfies components["schemas"]["HealthStatus"];

export const identityFixture = {
  user_id: "11111111-1111-4111-8111-111111111111",
  tenant_id: "22222222-2222-4222-8222-222222222222",
  role: "user",
} satisfies components["schemas"]["CurrentIdentity"];

export const unauthorizedFixture = {
  error: {
    code: "unauthorized",
    message: "Invalid token",
    request_id: "request-123",
    retryable: false,
    details: {},
  },
} satisfies components["schemas"]["ErrorEnvelope"];
