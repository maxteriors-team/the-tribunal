"use client";

/**
 * `FormDialog` — the canonical dialog shell for forms.
 *
 * Pairs with {@link useFormDialog} to remove the boilerplate every form dialog
 * repeated: the `Dialog`/`DialogContent`/header markup, the `Form` provider,
 * the `<form onSubmit>` wiring, and a standard Cancel + submit footer with a
 * loading spinner and busy label.
 *
 * Usage:
 *
 *   const dialog = useFormDialog({ open, onOpenChange, schema, defaultValues, onSubmit });
 *   return (
 *     <FormDialog
 *       dialog={dialog}
 *       title="Create Pipeline"
 *       description="Create a new sales pipeline."
 *       submitLabel="Create Pipeline"
 *       submitBusyLabel="Creating..."
 *     >
 *       <FormField ... />
 *     </FormDialog>
 *   );
 */

import { Loader2 } from "lucide-react";
import type * as React from "react";
import type { FieldValues } from "react-hook-form";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Form } from "@/components/ui/form";
import type { UseFormDialogReturn } from "@/lib/forms/use-form-dialog";
import { cn } from "@/lib/utils";

export interface FormDialogProps<TFieldValues extends FieldValues> {
  /** The controller returned by {@link useFormDialog}. */
  dialog: UseFormDialogReturn<TFieldValues>;
  /** Whether the dialog is open (controlled by the parent). */
  open: boolean;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Form fields. Rendered inside the shared `Form` provider + `<form>`. */
  children: React.ReactNode;
  /** Idle submit button label. Defaults to "Save". */
  submitLabel?: React.ReactNode;
  /** Submit button label while submitting. Defaults to `submitLabel`. */
  submitBusyLabel?: React.ReactNode;
  /** Cancel button label. Defaults to "Cancel". */
  cancelLabel?: React.ReactNode;
  /** Disable the submit button independently of the in-flight guard. */
  submitDisabled?: boolean;
  /** Submit button variant (e.g. "destructive"). Defaults to "default". */
  submitVariant?: React.ComponentProps<typeof Button>["variant"];
  /** Hide the default Cancel button. */
  hideCancel?: boolean;
  /** Extra footer content rendered before the Cancel/submit buttons. */
  footerExtra?: React.ReactNode;
  /** className applied to `DialogContent`. */
  className?: string;
  /** className applied to the scrolling field area. Defaults to "space-y-4". */
  formClassName?: string;
}

export function FormDialog<TFieldValues extends FieldValues>({
  dialog,
  open,
  title,
  description,
  children,
  submitLabel = "Save",
  submitBusyLabel,
  cancelLabel = "Cancel",
  submitDisabled = false,
  submitVariant = "default",
  hideCancel = false,
  footerExtra,
  className,
  formClassName,
}: FormDialogProps<TFieldValues>) {
  const { form, onOpenChange, handleSubmit, isSubmitting } = dialog;
  const busyLabel = submitBusyLabel ?? submitLabel;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/*
        Capped at the viewport with the fields as the only scrolling part, so a
        long form (the contact form runs past 20 fields) can never push its own
        title or its Save button off-screen. Short forms are unaffected: this is
        a ceiling, not a fixed height. `dvh` rather than `vh` so a mobile
        browser's retracting URL bar doesn't crop the footer.
      */}
      <DialogContent className={cn("flex max-h-[min(90dvh,52rem)] flex-col", className)}>
        <DialogHeader className="shrink-0">
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col gap-4">
            {/*
              `-mx-1 px-1` keeps input focus rings from being clipped by the
              scroll container's edge; `overscroll-contain` stops a scroll that
              reaches the end of the fields from scrolling the page behind.
            */}
            <div
              className={cn(
                "-mx-1 min-h-0 flex-1 overflow-y-auto overscroll-contain px-1 space-y-4",
                formClassName,
              )}
            >
              {children}
            </div>

            <DialogFooter className="shrink-0">
              {footerExtra}
              {!hideCancel && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => onOpenChange(false)}
                  disabled={isSubmitting}
                >
                  {cancelLabel}
                </Button>
              )}
              <Button type="submit" variant={submitVariant} disabled={isSubmitting || submitDisabled}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isSubmitting ? busyLabel : submitLabel}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
