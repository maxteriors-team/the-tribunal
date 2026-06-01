/**
 * API error extraction helpers for forms.
 *
 * Centralizes how we pull human-readable messages and field-level errors out
 * of API failures so every dialog/form treats backend errors the same way.
 *
 * Backend error shapes handled:
 *   - Canonical envelope: `{ code, message, request_id, details? }`
 *     (see backend `app/main.py` / `app/api/service_errors.py`). `details`
 *     may carry a per-field map: `{ email: "already taken" }` or
 *     `{ email: ["already taken"] }`.
 *   - FastAPI request validation (HTTP 422): `{ detail: [{ loc, msg, type }] }`.
 *   - Standard `Error` instances and unknown values (fall back).
 */

import type { FieldValues, Path, UseFormReturn } from "react-hook-form";

import { getApiErrorMessage } from "@/lib/utils/errors";

export { getApiErrorMessage };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function responseData(err: unknown): Record<string, unknown> | undefined {
  if (!isRecord(err) || !("response" in err)) return undefined;
  const response = (err as { response?: unknown }).response;
  if (!isRecord(response)) return undefined;
  const data = (response as { data?: unknown }).data;
  return isRecord(data) ? data : undefined;
}

function firstString(value: unknown): string | undefined {
  if (typeof value === "string" && value.length > 0) return value;
  if (Array.isArray(value)) {
    const first = value.find((item) => typeof item === "string" && item.length > 0);
    return typeof first === "string" ? first : undefined;
  }
  return undefined;
}

/**
 * Extract a `{ field: message }` map from a backend error.
 *
 * Returns an empty object when the error carries no per-field information.
 * Field names mirror the backend payload — callers can remap them to form
 * field paths via {@link applyApiErrorsToForm}'s `fieldMap`.
 */
export function getApiFieldErrors(err: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  const data = responseData(err);
  if (!data) return out;

  // FastAPI 422: `detail` is a list of `{ loc: [...], msg }`. The last
  // non-"body" location segment is the offending field name.
  const detail = data.detail;
  if (Array.isArray(detail)) {
    for (const item of detail) {
      if (!isRecord(item)) continue;
      const loc = item.loc;
      const msg = item.msg;
      if (!Array.isArray(loc) || loc.length === 0 || typeof msg !== "string") continue;
      const segments = loc.map(String).filter((segment) => segment !== "body");
      const field = segments[segments.length - 1];
      if (field && !(field in out)) out[field] = msg;
    }
    return out;
  }

  // Canonical envelope: `details` is a per-field map of string | string[].
  const details = data.details;
  if (isRecord(details)) {
    for (const [field, value] of Object.entries(details)) {
      const message = firstString(value);
      if (message) out[field] = message;
    }
  }
  return out;
}

export interface ApplyApiErrorsOptions<TFieldValues extends FieldValues> {
  /** Fallback message used when no specific message is found in the error. */
  fallback: string;
  /**
   * Allowlist of form field paths that may receive a server error. When
   * provided, only these fields are set (extra backend fields are ignored and
   * routed to `onTopLevelError`). Omit to set every detected field.
   */
  fields?: readonly Path<TFieldValues>[];
  /** Remap backend field names to form field paths (e.g. `slug` → `slug`). */
  fieldMap?: Partial<Record<string, Path<TFieldValues>>>;
  /** Called with the top-level message when no field error was applied. */
  onTopLevelError?: (message: string) => void;
}

/**
 * Apply a backend error to a react-hook-form instance.
 *
 * Sets `type: "server"` field errors for any per-field messages the backend
 * returned (subject to the `fields` allowlist / `fieldMap`). When no field
 * error is applied, the top-level message is passed to `onTopLevelError`
 * (typically `toast.error`).
 *
 * Returns the fields it touched and the resolved top-level message so callers
 * can branch further if needed.
 */
export function applyApiErrorsToForm<TFieldValues extends FieldValues>(
  form: UseFormReturn<TFieldValues>,
  err: unknown,
  options: ApplyApiErrorsOptions<TFieldValues>,
): { handledFields: Path<TFieldValues>[]; message: string } {
  const fieldErrors = getApiFieldErrors(err);
  const allow = options.fields ? new Set<string>(options.fields as readonly string[]) : undefined;
  const handled: Path<TFieldValues>[] = [];

  for (const [rawField, message] of Object.entries(fieldErrors)) {
    const target = (options.fieldMap?.[rawField] ?? rawField) as Path<TFieldValues>;
    if (allow && !allow.has(target as string)) continue;
    form.setError(target, { type: "server", message });
    handled.push(target);
  }

  const message = getApiErrorMessage(err, options.fallback);
  if (handled.length === 0) {
    options.onTopLevelError?.(message);
  }
  return { handledFields: handled, message };
}
