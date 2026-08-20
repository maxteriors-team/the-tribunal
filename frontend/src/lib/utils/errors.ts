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

/**
 * Maps sign-in failures to non-enumerating, actionable copy without exposing
 * Axios transport details or backend internals.
 */
export function getLoginErrorMessage(err: unknown): string {
  const status = getApiErrorStatus(err);

  if (status === 401) {
    return "Email or password is incorrect. Try again or reset your password.";
  }
  if (status === 429) {
    return "Too many sign-in attempts. Wait a few minutes, then try again.";
  }
  if (status === null) {
    return "We couldn't reach the sign-in service. Check your connection and try again.";
  }
  return "We couldn't sign you in right now. Try again in a moment.";
}

/**
 * Extracts the structured `details` payload from the canonical backend error
 * envelope (`{ code, message, details, request_id }`) on an Axios-style error.
 *
 * Returns `null` when the error carries no structured detail. Use this when a
 * rejection is meant to be *acted on* rather than only read: a blocking attach
 * rule rejects the save with the same warning object the advisory path returns
 * on success, so the builder can offer "Add gutters" instead of only reporting
 * a 400. Callers narrow the result themselves — it is server data, not a
 * guarantee.
 */
export function getApiErrorDetails(err: unknown): unknown {
  if (typeof err === "object" && err !== null && "response" in err) {
    const axErr = err as { response?: { data?: { details?: unknown } } };
    return axErr.response?.data?.details ?? null;
  }
  return null;
}

const PROVIDER_CONFIGURATION_ERROR_CODES = new Set([
  "provider_not_configured",
  "provider_configuration_missing",
  "telnyx_not_configured",
  "telnyx_provider_not_configured",
  "openai_not_configured",
  "openai_provider_not_configured",
  "ad_library_provider_not_configured",
  // This backend code is intentionally configuration-only: it is emitted by
  // the ad-library preflight when no usable workspace/provider credentials exist.
  "ad_library_provider_unavailable",
  "scraping_provider_not_configured",
  "people_search_provider_not_configured",
]);

const LEGACY_CONFIGURATION_MESSAGE =
  /(?:not|isn['’]t|is not) configured|no [^.]*credentials configured|(?:missing|needs?) (?:an? )?[^.]*api key/i;

/**
 * Identifies provider setup failures that retrying cannot repair.
 *
 * New endpoints should return a machine-readable code above. The message fallback
 * keeps older deployed backends actionable during rolling frontend deployments.
 */
export function isProviderConfigurationError(err: unknown): boolean {
  const code = getApiErrorCode(err);
  if (code && PROVIDER_CONFIGURATION_ERROR_CODES.has(code)) return true;

  return LEGACY_CONFIGURATION_MESSAGE.test(getApiErrorMessage(err, ""));
}

/**
 * Matches the app-wide React Query error-boundary policy while keeping expected
 * provider setup failures inside the feature that can explain how to fix them.
 */
export function shouldThrowProviderError(err: unknown): boolean {
  const status = getApiErrorStatus(err);
  return status !== null && status >= 500 && !isProviderConfigurationError(err);
}
