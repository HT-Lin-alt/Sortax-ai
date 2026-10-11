export interface ErrorPayload {
  readonly code: string;
  readonly message: string;
  readonly request_id?: string;
  readonly retryable?: boolean;
  readonly retry_after_seconds?: number;
  readonly details?: Readonly<Record<string, unknown>>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly retryable: boolean;
  readonly retryAfterSeconds: number | null;

  constructor(status: number, payload: ErrorPayload) {
    super(payload.message);
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code;
    this.requestId = payload.request_id ?? null;
    this.retryable = payload.retryable ?? false;
    this.retryAfterSeconds = payload.retry_after_seconds ?? null;
  }
}

export async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: ErrorPayload = {
    code: "invalid_response",
    message: "The service returned an unexpected error.",
  };
  try {
    const body: unknown = await response.json();
    if (isErrorEnvelope(body)) {
      payload = body.error;
    }
  } catch {
    // Preserve the stable fallback and never expose an untrusted response body.
  }
  return new ApiError(response.status, payload);
}

function isErrorEnvelope(value: unknown): value is { readonly error: ErrorPayload } {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const error = value.error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof error.code === "string" &&
    "message" in error &&
    typeof error.message === "string"
  );
}
