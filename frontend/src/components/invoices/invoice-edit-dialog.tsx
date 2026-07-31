"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { CatalogPicker } from "@/components/catalog/catalog-picker";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { invoicesApi } from "@/lib/api/invoices";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Invoice } from "@/types";

const moneyString = z
  .string()
  .trim()
  .refine((v) => v === "" || (!Number.isNaN(Number(v)) && Number(v) >= 0), {
    error: "Enter a valid amount",
  });

const lineItemSchema = z.object({
  name: z.string().trim().min(1, { error: "Name is required" }),
  quantity: z
    .string()
    .trim()
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, {
      error: "Qty > 0",
    }),
  unit_price: z
    .string()
    .trim()
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) >= 0, {
      error: "Enter a price",
    }),
});

const editInvoiceSchema = z.object({
  due_date: z.string(),
  tax_amount: moneyString,
  notes: z.string(),
  terms: z.string(),
  line_items: z
    .array(lineItemSchema)
    .min(1, { error: "An invoice needs at least one line item" }),
});

type EditInvoiceFormValues = z.infer<typeof editInvoiceSchema>;

const EMPTY_LINE = { name: "", quantity: "1", unit_price: "" } as const;

interface InvoiceEditDialogProps {
  invoice: Invoice | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Edit an existing invoice.
 *
 * Mirrors the backend's mutability rules rather than inventing its own:
 * line items are frozen once an invoice is `paid` (it's a receipt at that
 * point), while notes/terms/due date stay editable so an operator can still
 * annotate history. A `void` invoice is not editable at all, so the row never
 * offers this dialog.
 *
 * Saves as a single `PUT` — the whole line-item set travels together so a
 * multi-row correction can't half-apply on a financial record.
 */
export function InvoiceEditDialog({
  invoice,
  open,
  onOpenChange,
}: InvoiceEditDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  // The list row carries no line items, so fetch the detail when opening.
  const detailQuery = useQuery({
    queryKey: queryKeys.invoices.detail(workspaceId ?? "", invoice?.id ?? ""),
    queryFn: () => invoicesApi.get(workspaceId ?? "", invoice?.id ?? ""),
    enabled: Boolean(workspaceId) && Boolean(invoice?.id) && open,
  });
  const detail = detailQuery.data;

  // Settled invoices keep their lines as history; the backend rejects the edit,
  // so the form must not offer it either.
  const lineItemsLocked = invoice?.status === "paid";
  // Already in the customer's inbox, with a live public link.
  const alreadySent = Boolean(
    invoice && invoice.status !== "draft" && invoice.status !== "void"
  );

  const form = useForm<EditInvoiceFormValues>({
    resolver: zodResolver(editInvoiceSchema),
    defaultValues: {
      due_date: "",
      tax_amount: "",
      notes: "",
      terms: "",
      line_items: [{ ...EMPTY_LINE }],
    },
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "line_items",
  });

  // Populate once the detail lands (and on reopen for a different invoice).
  useEffect(() => {
    if (!open || !detail) return;
    form.reset({
      due_date: detail.due_date ?? "",
      tax_amount: detail.tax_amount ? String(detail.tax_amount) : "",
      notes: detail.notes ?? "",
      terms: detail.terms ?? "",
      line_items: detail.line_items?.length
        ? detail.line_items.map((li) => ({
            name: li.name,
            quantity: String(li.quantity),
            unit_price: String(li.unit_price),
          }))
        : [{ ...EMPTY_LINE }],
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, detail?.id, detail?.updated_at]);

  const saveMutation = useMutation({
    mutationFn: async (values: EditInvoiceFormValues): Promise<Invoice> => {
      if (!workspaceId || !invoice) throw new Error("No invoice selected");
      return invoicesApi.update(workspaceId, invoice.id, {
        // The API ignores nulls (it skips unset fields), so an emptied text box
        // is sent as "" to actually clear it. An emptied date can't be cleared
        // this way -- "" isn't a valid date -- so it is omitted instead.
        ...(values.due_date ? { due_date: values.due_date } : {}),
        tax_amount: values.tax_amount ? Number(values.tax_amount) : 0,
        notes: values.notes,
        terms: values.terms,
        // Omitted entirely when locked, so a paid invoice's lines are never
        // even submitted for the server to reject.
        ...(lineItemsLocked
          ? {}
          : {
              line_items: values.line_items.map((li) => ({
                name: li.name,
                quantity: Number(li.quantity),
                unit_price: Number(li.unit_price),
              })),
            }),
      });
    },
    onSuccess: (updated) => {
      toast.success(`Invoice ${updated.number} updated`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.invoices.all(workspaceId ?? ""),
      });
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Could not update the invoice"));
    },
  });

  const watchedLines = useWatch({ control: form.control, name: "line_items" });
  const watchedTax = useWatch({ control: form.control, name: "tax_amount" });
  const subtotal = (watchedLines ?? []).reduce((sum, li) => {
    const qty = Number(li?.quantity) || 0;
    const price = Number(li?.unit_price) || 0;
    return sum + qty * price;
  }, 0);
  const total = subtotal + (Number(watchedTax) || 0);
  const alreadyPaid = detail?.amount_paid ?? 0;

  const handleOpenChange = (next: boolean) => {
    if (!next && saveMutation.isPending) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            Edit invoice {invoice?.number ? `${invoice.number}` : ""}
          </DialogTitle>
          <DialogDescription>
            {lineItemsLocked
              ? "This invoice is paid, so its line items are locked. You can still update the notes and terms."
              : alreadySent
                ? "This invoice has already been sent. Saving updates what the customer sees on their invoice link."
                : "Update this draft before sending it."}
          </DialogDescription>
        </DialogHeader>

        {detailQuery.isLoading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : detailQuery.isError ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Could not load this invoice. Close and try again.
          </p>
        ) : (
          <Form {...form}>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                form.handleSubmit((values) => saveMutation.mutate(values))();
              }}
              className="space-y-5 py-4"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <FormLabel>Line items</FormLabel>
                  {!lineItemsLocked && (
                    <div className="flex items-center gap-2">
                      <CatalogPicker
                        disabled={saveMutation.isPending}
                        onPick={(item) =>
                          append({
                            name: item.name,
                            quantity: "1",
                            unit_price: String(item.unit_price),
                          })
                        }
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => append({ ...EMPTY_LINE })}
                        disabled={saveMutation.isPending}
                      >
                        <Plus className="mr-1 h-3.5 w-3.5" />
                        Add line
                      </Button>
                    </div>
                  )}
                </div>

                {fields.map((field, index) => (
                  <div
                    key={field.id}
                    className="grid grid-cols-[1fr_5rem_7rem_auto] items-start gap-2"
                  >
                    <FormField
                      control={form.control}
                      name={`line_items.${index}.name`}
                      render={({ field: f }) => (
                        <FormItem>
                          <FormControl>
                            <Input
                              placeholder="Description"
                              disabled={lineItemsLocked}
                              {...f}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`line_items.${index}.quantity`}
                      render={({ field: f }) => (
                        <FormItem>
                          <FormControl>
                            <Input
                              type="number"
                              min="0"
                              step="1"
                              inputMode="decimal"
                              placeholder="Qty"
                              disabled={lineItemsLocked}
                              {...f}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`line_items.${index}.unit_price`}
                      render={({ field: f }) => (
                        <FormItem>
                          <FormControl>
                            <Input
                              type="number"
                              min="0"
                              step="0.01"
                              inputMode="decimal"
                              placeholder="Price"
                              disabled={lineItemsLocked}
                              {...f}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="mt-0.5"
                      onClick={() =>
                        fields.length > 1 ? remove(index) : undefined
                      }
                      disabled={
                        lineItemsLocked ||
                        fields.length <= 1 ||
                        saveMutation.isPending
                      }
                      aria-label="Remove line item"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <FormField
                  control={form.control}
                  name="due_date"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Due date</FormLabel>
                      <FormControl>
                        <Input type="date" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="tax_amount"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tax</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min="0"
                          step="0.01"
                          inputMode="decimal"
                          placeholder="0.00"
                          disabled={lineItemsLocked}
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="notes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Notes</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Optional note shown on the invoice..."
                        className="min-h-[60px]"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="terms"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Terms</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Payment terms shown on the invoice..."
                        className="min-h-[60px]"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="space-y-1 border-t pt-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Total</span>
                  <span className="text-base font-semibold">
                    {formatCurrency(total)}
                  </span>
                </div>
                {alreadyPaid > 0 && (
                  // Re-pricing an invoice the customer part-paid changes what
                  // they still owe; show the arithmetic rather than surprising
                  // them with a new balance on their link.
                  <>
                    <div className="flex items-center justify-between text-muted-foreground">
                      <span>Already paid</span>
                      <span>−{formatCurrency(alreadyPaid)}</span>
                    </div>
                    <div className="flex items-center justify-between font-medium">
                      <span>Balance due</span>
                      <span>
                        {formatCurrency(Math.max(0, total - alreadyPaid))}
                      </span>
                    </div>
                  </>
                )}
              </div>

              <DialogFooter className="gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => handleOpenChange(false)}
                  disabled={saveMutation.isPending}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={saveMutation.isPending}>
                  {saveMutation.isPending && (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  )}
                  Save changes
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
