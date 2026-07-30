/**
 * Extracts a human-readable error message from an unknown error value.
 *
 * Handles:
 * - Axios-style errors with `response.data.message` (canonical backend shape:
 *   `{ code, message, request_id }`)
 * - Axios-style errors with `response.data.detail` (legacy / FastAPI default
 *   validation error shape)
 * - Standard `Error` instances
 * - Falls back to the provided `fallback` string
 */
export function getApiErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === "object" && err !== null && "response" in err) {
    const axErr = err as {
      response?: { data?: { message?: unknown; detail?: unknown } };
    };
    const data = axErr.response?.data;
    if (data && typeof data.message === "string" && data.message.length > 0) {
      return data.message;
    }
    if (data && typeof data.detail === "string" && data.detail.length > 0) {
      return data.detail;
    }
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/**
 * Extracts the machine-readable error `code` from the canonical backend error
 * envelope (`{ code, message, request_id }`) on an Axios-style error.
 *
 * Returns `null` when no structured code is present (network errors, plain
 * `Error`s, or the legacy FastAPI `detail` string shape). Use this to branch UI
 * on specific server conditions (e.g. `provider_not_configured`) rather than
 * brittle message-string matching.
 */
export function getApiErrorCode(err: unknown): string | null {
  if (typeof err === "object" && err !== null && "response" in err) {
    const axErr = err as { response?: { data?: { code?: unknown } } };
    const code = axErr.response?.data?.code;
    if (typeof code === "string" && code.length > 0) return code;
  }
  return null;
}

/**
 * Extracts the HTTP status code from an Axios-style error, or `null` for a
 * network/transport failure that never reached the server.
 *
 * Use it to distinguish an *expected* status from a real fault — e.g. a 404 that
 * simply means "this resource has not been created yet" should render an empty
 * state and must not be retried.
 */
export function getApiErrorStatus(err: unknown): number | null {
  if (typeof err === "object" && err !== null && "response" in err) {
    const axErr = err as { response?: { status?: unknown } };
    const status = axErr.response?.status;
    if (typeof status === "number") return status;
  }
  return null;
}
