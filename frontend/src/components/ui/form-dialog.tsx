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
  /** className applied to the inner `<form>`. Defaults to "space-y-4". */
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
      <DialogContent className={className}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={handleSubmit} className={cn("space-y-4", formClassName)}>
            {children}

            <DialogFooter>
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
