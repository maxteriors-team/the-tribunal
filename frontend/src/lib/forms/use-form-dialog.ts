"use client";

/**
 * `useFormDialog` — the canonical wiring for a dialog that hosts a form.
 *
 * Bundles the conventions every form dialog in the app repeated by hand:
 *   - zod + react-hook-form via `zodResolver`
 *   - reset-on-close (and reset-to-new-defaults when defaults change while open,
 *     e.g. an "edit" dialog whose record changes)
 *   - a single in-flight submit guard with derived `isSubmitting`
 *   - server error → field/top-level mapping via {@link applyApiErrorsToForm}
 *
 * The hook is headless: it returns the `form`, an `onOpenChange` to pass to the
 * dialog, a `handleSubmit` to pass to `<form onSubmit>`, and `isSubmitting` for
 * the submit button. Render with `<FormDialog>` or a plain `<Dialog>`.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useCallback, useEffect, useRef } from "react";
import {
  useForm,
  type DefaultValues,
  type FieldValues,
  type Path,
  type Resolver,
  type UseFormProps,
  type UseFormReturn,
} from "react-hook-form";
import type { ZodType } from "zod";

import { applyApiErrorsToForm } from "@/lib/forms/api-errors";

export interface UseFormDialogOptions<TFieldValues extends FieldValues> {
  /** Controlled open state of the dialog. */
  open: boolean;
  /** Controlled open-state setter (typically from the parent). */
  onOpenChange: (open: boolean) => void;
  /** Zod schema validated on submit. */
  schema: ZodType<TFieldValues, TFieldValues>;
  /** Initial values. Changing these while open re-syncs the form (edit dialogs). */
  defaultValues: DefaultValues<TFieldValues>;
  /**
   * Submit handler for valid values. Throw to surface a server error — the hook
   * routes it to field/top-level errors and keeps the dialog open. Resolve to
   * let your own success handler close the dialog.
   */
  onSubmit: (values: TFieldValues, form: UseFormReturn<TFieldValues>) => Promise<void> | void;
  /** Fallback toast/message when a thrown error carries no readable message. */
  errorFallback?: string;
  /** Allowlist of form fields that may receive a server-side field error. */
  serverErrorFields?: readonly Path<TFieldValues>[];
  /** Remap backend field names to form field paths. */
  serverErrorFieldMap?: Partial<Record<string, Path<TFieldValues>>>;
  /** Called with the top-level message when a submit error isn't field-specific. */
  onTopLevelError?: (message: string) => void;
  /** Reset the form when the dialog closes. Defaults to `true`. */
  resetOnClose?: boolean;
  /** Extra `useForm` options (e.g. `mode`). `resolver`/`defaultValues` are managed. */
  formProps?: Omit<UseFormProps<TFieldValues>, "resolver" | "defaultValues">;
}

export interface UseFormDialogReturn<TFieldValues extends FieldValues> {
  form: UseFormReturn<TFieldValues>;
  /** Pass to the dialog's `onOpenChange`; guards close while submitting + resets. */
  onOpenChange: (open: boolean) => void;
  /** Pass to `<form onSubmit={...}>`. */
  handleSubmit: (event?: React.BaseSyntheticEvent) => Promise<void>;
  /** True while a submit is in flight. Use for the submit button's disabled/spinner. */
  isSubmitting: boolean;
  /** Programmatically close the dialog (respects the in-flight guard). */
  close: () => void;
}

function stableKey(values: unknown): string {
  try {
    return JSON.stringify(values);
  } catch {
    return "";
  }
}

export function useFormDialog<TFieldValues extends FieldValues>(
  options: UseFormDialogOptions<TFieldValues>,
): UseFormDialogReturn<TFieldValues> {
  const {
    open,
    onOpenChange,
    schema,
    defaultValues,
    onSubmit,
    errorFallback = "Something went wrong. Please try again.",
    serverErrorFields,
    serverErrorFieldMap,
    onTopLevelError,
    resetOnClose = true,
    formProps,
  } = options;

  const form = useForm<TFieldValues>({
    ...formProps,
    resolver: zodResolver(schema) as Resolver<TFieldValues>,
    defaultValues,
  });

  // Keep the latest submit handler without re-subscribing handleSubmit. Updated
  // in an effect (not during render) so refs aren't mutated while rendering.
  const submitRef = useRef(onSubmit);
  useEffect(() => {
    submitRef.current = onSubmit;
  }, [onSubmit]);

  // Drive reset behavior off the `open` prop so it covers every close path:
  //   - user-initiated (Cancel / escape / overlay) via `handleOpenChange`, and
  //   - programmatic (a successful submit calling the parent's `onOpenChange`),
  //     which Radix never routes through `handleOpenChange`.
  // Tracking `open` here (rather than only in the close handler) is what makes
  // reset-on-close reliable after a successful submit.
  const defaultsKey = stableKey(defaultValues);
  const lastDefaultsKey = useRef(defaultsKey);
  const wasOpen = useRef(open);
  useEffect(() => {
    const openChanged = wasOpen.current !== open;
    const defaultsChanged = defaultsKey !== lastDefaultsKey.current;
    wasOpen.current = open;
    lastDefaultsKey.current = defaultsKey;

    // Edit dialog adopted a new record (or opened onto new defaults) while open.
    if (open && defaultsChanged) {
      form.reset(defaultValues);
      return;
    }
    // Dialog closed by any path — restore pristine defaults.
    if (openChanged && !open && resetOnClose) {
      form.reset(defaultValues);
    }
    // `defaultValues` is intentionally tracked via its serialized key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultsKey, resetOnClose, form]);

  const handleOpenChange = useCallback(
    (next: boolean) => {
      // Don't let an overlay/escape close swallow an in-flight submit. The
      // reset itself is handled by the `open`-watching effect above.
      if (!next && form.formState.isSubmitting) return;
      onOpenChange(next);
    },
    [form, onOpenChange],
  );

  const handleSubmit = useCallback(
    (event?: React.BaseSyntheticEvent) =>
      form.handleSubmit(async (values) => {
        try {
          await submitRef.current(values, form);
        } catch (err) {
          applyApiErrorsToForm(form, err, {
            fallback: errorFallback,
            fields: serverErrorFields,
            fieldMap: serverErrorFieldMap,
            onTopLevelError,
          });
        }
      })(event),
    [form, errorFallback, serverErrorFields, serverErrorFieldMap, onTopLevelError],
  );

  const close = useCallback(() => handleOpenChange(false), [handleOpenChange]);

  return {
    form,
    onOpenChange: handleOpenChange,
    handleSubmit,
    isSubmitting: form.formState.isSubmitting,
    close,
  };
}
