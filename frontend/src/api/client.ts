import type { components } from "./generated-types";
import { errorFromResponse } from "./errors";

export type HealthStatus = components["schemas"]["HealthStatus"];
export type CurrentIdentity = components["schemas"]["CurrentIdentity"];

interface RequestOptions {
  readonly signal?: AbortSignal;
}

interface AuthorizedRequestOptions extends RequestOptions {
  readonly accessToken: string;
}

export async function getLiveHealth(options: RequestOptions = {}): Promise<HealthStatus> {
  return requestJson<HealthStatus>("/health/live", options);
}

export async function getCurrentIdentity(
  options: AuthorizedRequestOptions,
): Promise<CurrentIdentity> {
  return requestJson<CurrentIdentity>("/api/v1/auth/me", options);
}

async function requestJson<T>(path: string, options: RequestOptions | AuthorizedRequestOptions) {
  const headers = new Headers({ Accept: "application/json" });
  if ("accessToken" in options) {
    headers.set("Authorization", `Bearer ${options.accessToken}`);
  }
  const requestInit: RequestInit = {
    method: "GET",
    headers,
  };
  if (options.signal !== undefined) {
    requestInit.signal = options.signal;
  }
  const response = await fetch(path, requestInit);
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  return (await response.json()) as T;
}
