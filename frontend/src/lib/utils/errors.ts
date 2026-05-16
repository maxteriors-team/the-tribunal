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
