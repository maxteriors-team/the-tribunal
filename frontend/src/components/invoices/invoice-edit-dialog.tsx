"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { CatalogPicker } from "@/components/catalog/catalog-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { describeInvoiceDelivery } from "@/lib/invoice-delivery";
import { queryKeys } from "@/lib/query-keys";
import { formatDateTime } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Invoice, InvoiceSendResult } from "@/types";

const RECEIPT_STATUS = {
  pending: { label: "Pending", variant: "secondary" },
  sent: { label: "Sent", variant: "default" },
  needs_attention: { label: "Needs attention", variant: "destructive" },
  skipped: { label: "Skipped", variant: "outline" },
} as const;

const moneyString = z
  .string()
  .trim()
  .refine((v) => v === "" || (!Number.isNaN(Number(v)) && Number(v) >= 0), {
    error: "Enter a valid amount",
  });

const lineItemSchema = z.object({
  name: z.string().trim().min(1, { error: "Name is required" }),
  description: z.string(),
  quantity: z
    .string()
    .trim()
    .min(1, { error: "Quantity is required" })
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) >= 0, {
      error: "Qty ≥ 0",
    }),
  unit_price: z
    .string()
    .trim()
    .min(1, { error: "Price is required" })
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) >= 0, {
      error: "Enter a price",
    }),
  discount: moneyString,
  is_optional: z.boolean(),
});

const editInvoiceSchema = z.object({
  due_date: z.string(),
  tax_amount: moneyString,
  discount_amount: moneyString,
  notes: z.string(),
  terms: z.string(),
  line_items: z.array(lineItemSchema).min(1, { error: "An invoice needs at least one line item" }),
});

type EditInvoiceFormValues = z.infer<typeof editInvoiceSchema>;

const EMPTY_LINE = {
  name: "",
  description: "",
  quantity: "1",
  unit_price: "",
  discount: "",
  is_optional: false,
} as const;

interface InvoiceEditDialogProps {
  invoice: Invoice | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface SaveInvoiceInput {
  values: EditInvoiceFormValues;
  resend: boolean;
}

interface SaveInvoiceResult {
  updated: Invoice;
  delivery?: InvoiceSendResult;
  deliveryError?: unknown;
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
 * Each correction is one `PUT` so a multi-row financial edit cannot half-apply.
 * A resend is a separate, explicit action performed only after that save succeeds.
 */
export function InvoiceEditDialog({ invoice, open, onOpenChange }: InvoiceEditDialogProps) {
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
  // so the form must not offer it either. Prefer the freshly loaded lifecycle
  // status over a potentially stale list row.
  const lifecycleStatus = detail?.status ?? invoice?.status;
  const lineItemsLocked = lifecycleStatus === "paid";
  const alreadySent = Boolean(
    (detail?.sent_at ?? invoice?.sent_at) ||
    (lifecycleStatus && lifecycleStatus !== "draft" && lifecycleStatus !== "void"),
  );

  const form = useForm<EditInvoiceFormValues>({
    resolver: zodResolver(editInvoiceSchema),
    defaultValues: {
      due_date: "",
      tax_amount: "",
      discount_amount: "",
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
      tax_amount: String(detail.tax_amount ?? 0),
      discount_amount: String(detail.discount_amount ?? 0),
      notes: detail.notes ?? "",
      terms: detail.terms ?? "",
      line_items: detail.line_items?.length
        ? detail.line_items.map((li) => ({
            name: li.name,
            description: li.description ?? "",
            quantity: String(li.quantity),
            unit_price: String(li.unit_price),
            discount: String(li.discount ?? 0),
            is_optional: li.is_optional,
          }))
        : [{ ...EMPTY_LINE }],
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, detail?.id, detail?.updated_at]);

  const saveMutation = useMutation({
    mutationFn: async ({ values, resend }: SaveInvoiceInput): Promise<SaveInvoiceResult> => {
      if (!workspaceId || !invoice) throw new Error("No invoice selected");
      const updated = await invoicesApi.update(workspaceId, invoice.id, {
        // Empty text boxes are sent as "" to actually clear them. An empty date
        // cannot be cleared this way because "" is not a valid API date.
        ...(values.due_date ? { due_date: values.due_date } : {}),
        notes: values.notes,
        terms: values.terms,
        // Paid invoices are annotation-only. Even unchanged amount fields must
        // be omitted because the backend rejects their presence by contract.
        ...(lineItemsLocked
          ? {}
          : {
              tax_amount: values.tax_amount ? Number(values.tax_amount) : 0,
              discount_amount: values.discount_amount ? Number(values.discount_amount) : 0,
              line_items: values.line_items.map((li) => ({
                name: li.name,
                description: li.description || null,
                quantity: Number(li.quantity),
                unit_price: Number(li.unit_price),
                discount: li.discount ? Number(li.discount) : 0,
                is_optional: li.is_optional,
              })),
            }),
      });

      if (!resend) return { updated };
      try {
        return { updated, delivery: await invoicesApi.send(workspaceId, updated.id) };
      } catch (deliveryError) {
        // The update is already committed. Return partial success so the UI never
        // tells the operator the correction was lost when only delivery failed.
        return { updated, deliveryError };
      }
    },
    onSuccess: ({ updated, delivery, deliveryError }, { resend }) => {
      if (!resend) {
        toast.success(`Invoice ${updated.number} updated without notifying the customer`);
      } else if (deliveryError) {
        toast.warning(`Invoice ${updated.number} correction saved, but resend failed`, {
          description: getApiErrorMessage(deliveryError, "The customer was not notified."),
        });
      } else if (delivery) {
        const notice = describeInvoiceDelivery(delivery);
        if (notice.tone === "success") {
          toast.success(`Correction saved. ${notice.message}`);
        } else {
          toast.warning(`Invoice ${updated.number} correction saved, but resend failed`, {
            description: notice.description,
          });
        }
      }
      void queryClient.invalidateQueries({
        queryKey: queryKeys.invoices.all(workspaceId ?? ""),
      });
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Could not update the invoice"));
    },
  });

  const retryReceiptMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !invoice) throw new Error("No invoice selected");
      return invoicesApi.retryReceipt(workspaceId, invoice.id);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.invoices.detail(workspaceId ?? "", updated.id), updated);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.invoices.list(workspaceId ?? ""),
      });
      toast.success(
        updated.receipt_delivery.status === "sent"
          ? `Receipt for ${updated.number} was already sent`
          : `Receipt for ${updated.number} queued`,
      );
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Could not retry the receipt"));
    },
  });

  const watchedLines = useWatch({ control: form.control, name: "line_items" });
  const watchedTax = useWatch({ control: form.control, name: "tax_amount" });
  const watchedDiscount = useWatch({ control: form.control, name: "discount_amount" });
  const grossLineTotal = (watchedLines ?? []).reduce((sum, li) => {
    const qty = Number(li?.quantity) || 0;
    const price = Number(li?.unit_price) || 0;
    return sum + qty * price;
  }, 0);
  const lineDiscountTotal = (watchedLines ?? []).reduce(
    (sum, li) => sum + (Number(li?.discount) || 0),
    0,
  );
  const subtotal = grossLineTotal - lineDiscountTotal;
  const tax = Number(watchedTax) || 0;
  const invoiceDiscount = Number(watchedDiscount) || 0;
  const total = subtotal + tax - invoiceDiscount;
  const alreadyPaid = detail?.amount_paid ?? 0;
  const currency = detail?.currency ?? invoice?.currency ?? "USD";
  const receiptDelivery = detail?.receipt_delivery ?? invoice?.receipt_delivery;
  const paymentHistory = detail?.payments ?? [];

  const submit = (resend: boolean) => {
    form.handleSubmit((values) => saveMutation.mutate({ values, resend }))();
  };

  const handleOpenChange = (next: boolean) => {
    if (!next && (saveMutation.isPending || retryReceiptMutation.isPending)) return;
    onOpenChange(next);
  };
  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit invoice {invoice?.number ? `${invoice.number}` : ""}</DialogTitle>
          <DialogDescription>
            {lineItemsLocked
              ? "This invoice is paid. Amounts and line items are locked; update its due date, notes, or terms, then choose whether to notify the customer."
              : alreadySent
                ? "This invoice has already been sent. Save without notifying, or save and resend the corrected invoice."
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
                submit(false);
              }}
              className="space-y-5 py-4"
            >
              {paymentHistory.length > 0 ? (
                <section className="rounded-md border p-3" aria-label="Payment history">
                  <p className="mb-2 text-sm font-medium">Payment history</p>
                  <div className="divide-y">
                    {paymentHistory.map((payment) => (
                      <div
                        key={payment.id}
                        className="flex items-start justify-between gap-3 py-2 first:pt-0 last:pb-0"
                      >
                        <div>
                          <p className="text-sm font-medium capitalize">
                            {payment.payment_method === "other"
                              ? "Imported payment"
                              : `${payment.payment_method} payment`}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {formatDateTime(payment.received_at)}
                          </p>
                          {payment.reference && (
                            <p className="text-xs text-muted-foreground">
                              Check number: {payment.reference}
                            </p>
                          )}
                        </div>
                        <p className="text-sm font-semibold">
                          {formatCurrency(payment.amount, currency)}
                        </p>
                      </div>
                    ))}
                  </div>
                </section>
              ) : (detail?.payment_method ?? invoice?.payment_method) ? (
                <section className="rounded-md border p-3" aria-label="Payment details">
                  <p className="text-sm font-medium capitalize">
                    Paid by {detail?.payment_method ?? invoice?.payment_method}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {formatCurrency(
                      detail?.manual_payment_amount ??
                        invoice?.manual_payment_amount ??
                        detail?.amount_paid ??
                        invoice?.amount_paid ??
                        0,
                      currency,
                    )}
                  </p>
                </section>
              ) : null}

              {receiptDelivery && (
                <section className="rounded-md border p-3" aria-label="Receipt delivery">
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium">Receipt delivery</p>
                        <Badge variant={RECEIPT_STATUS[receiptDelivery.status].variant}>
                          {RECEIPT_STATUS[receiptDelivery.status].label}
                        </Badge>
                      </div>
                      {receiptDelivery.recipient && (
                        <p className="text-sm text-muted-foreground">
                          Recipient: {receiptDelivery.recipient}
                        </p>
                      )}
                      {receiptDelivery.timestamp && (
                        <p className="text-xs text-muted-foreground">
                          Updated {formatDateTime(receiptDelivery.timestamp)}
                        </p>
                      )}
                      {receiptDelivery.reason && (
                        <p className="text-sm text-destructive">{receiptDelivery.reason}</p>
                      )}
                    </div>
                    {receiptDelivery.status === "needs_attention" && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => retryReceiptMutation.mutate()}
                        disabled={retryReceiptMutation.isPending}
                      >
                        {retryReceiptMutation.isPending ? (
                          <Loader2 className="mr-2 size-4 animate-spin" />
                        ) : (
                          <RotateCcw className="mr-2 size-4" />
                        )}
                        Retry receipt
                      </Button>
                    )}
                  </div>
                </section>
              )}

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
                            description: "",
                            quantity: "1",
                            unit_price: String(item.unit_price),
                            discount: "",
                            is_optional: false,
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

                {fields.map((lineField, index) => (
                  <div
                    key={lineField.id}
                    className="grid grid-cols-12 items-start gap-2 rounded-md border p-3"
                  >
                    <FormField
                      control={form.control}
                      name={`line_items.${index}.name`}
                      render={({ field: f }) => (
                        <FormItem className="col-span-12 sm:col-span-5">
                          <FormControl>
                            <Input
                              aria-label={`Line item ${index + 1} name`}
                              placeholder="Item name"
                              disabled={lineItemsLocked || saveMutation.isPending}
                              {...f}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`line_items.${index}.description`}
                      render={({ field: f }) => (
                        <FormItem className="col-span-12 sm:col-span-7">
                          <FormControl>
                            <Input
                              aria-label={`Line item ${index + 1} description`}
                              placeholder="Optional details"
                              disabled={lineItemsLocked || saveMutation.isPending}
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
                        <FormItem className="col-span-4 sm:col-span-3">
                          <FormControl>
                            <Input
                              type="number"
                              min="0"
                              step="any"
                              inputMode="decimal"
                              aria-label={`Line item ${index + 1} quantity`}
                              placeholder="Qty"
                              disabled={lineItemsLocked || saveMutation.isPending}
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
                        <FormItem className="col-span-4 sm:col-span-4">
                          <FormControl>
                            <Input
                              type="number"
                              min="0"
                              step="0.01"
                              inputMode="decimal"
                              aria-label={`Line item ${index + 1} price`}
                              placeholder="Price"
                              disabled={lineItemsLocked || saveMutation.isPending}
                              {...f}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`line_items.${index}.discount`}
                      render={({ field: f }) => (
                        <FormItem className="col-span-4 sm:col-span-4">
                          <FormControl>
                            <Input
                              type="number"
                              min="0"
                              step="0.01"
                              inputMode="decimal"
                              aria-label={`Line item ${index + 1} discount`}
                              placeholder="Discount"
                              disabled={lineItemsLocked || saveMutation.isPending}
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
                      className="col-span-12 justify-self-end sm:col-span-1"
                      onClick={() => (fields.length > 1 ? remove(index) : undefined)}
                      disabled={lineItemsLocked || fields.length <= 1 || saveMutation.isPending}
                      aria-label={`Remove line item ${index + 1}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                    <FormField
                      control={form.control}
                      name={`line_items.${index}.is_optional`}
                      render={({ field: f }) => {
                        const checkboxId = `edit-line-${lineField.id}-optional`;
                        return (
                          <FormItem className="col-span-12 flex items-center gap-2 space-y-0">
                            <FormControl>
                              <Checkbox
                                id={checkboxId}
                                checked={f.value}
                                onCheckedChange={(checked) => f.onChange(checked === true)}
                                disabled={lineItemsLocked || saveMutation.isPending}
                              />
                            </FormControl>
                            <FormLabel htmlFor={checkboxId} className="font-normal">
                              Optional item
                            </FormLabel>
                          </FormItem>
                        );
                      }}
                    />
                  </div>
                ))}
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <FormField
                  control={form.control}
                  name="due_date"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Due date</FormLabel>
                      <FormControl>
                        <Input type="date" disabled={saveMutation.isPending} {...field} />
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
                          disabled={lineItemsLocked || saveMutation.isPending}
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="discount_amount"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Invoice discount</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min="0"
                          step="0.01"
                          inputMode="decimal"
                          placeholder="0.00"
                          disabled={lineItemsLocked || saveMutation.isPending}
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
                        disabled={saveMutation.isPending}
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
                        disabled={saveMutation.isPending}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="space-y-1 border-t pt-3 text-sm" aria-label="Invoice total preview">
                <div className="flex items-center justify-between text-muted-foreground">
                  <span>Line items</span>
                  <span>{formatCurrency(grossLineTotal, currency)}</span>
                </div>
                <div className="flex items-center justify-between text-muted-foreground">
                  <span>Line discounts</span>
                  <span>−{formatCurrency(lineDiscountTotal, currency)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Subtotal</span>
                  <span>{formatCurrency(subtotal, currency)}</span>
                </div>
                <div className="flex items-center justify-between text-muted-foreground">
                  <span>Tax</span>
                  <span>+{formatCurrency(tax, currency)}</span>
                </div>
                <div className="flex items-center justify-between text-muted-foreground">
                  <span>Invoice discount</span>
                  <span>−{formatCurrency(invoiceDiscount, currency)}</span>
                </div>
                <div className="mt-2 flex items-center justify-between border-t pt-2">
                  <span className="text-muted-foreground">Total</span>
                  <span className="text-base font-semibold">{formatCurrency(total, currency)}</span>
                </div>
                {alreadyPaid > 0 && (
                  // Re-pricing an invoice the customer part-paid changes what
                  // they still owe; show the arithmetic rather than surprising
                  // them with a new balance on their link.
                  <>
                    <div className="flex items-center justify-between text-muted-foreground">
                      <span>Already paid</span>
                      <span>−{formatCurrency(alreadyPaid, currency)}</span>
                    </div>
                    <div className="flex items-center justify-between font-medium">
                      <span>Balance due</span>
                      <span>{formatCurrency(Math.max(0, total - alreadyPaid), currency)}</span>
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
                {alreadySent ? (
                  <>
                    <Button type="submit" variant="outline" disabled={saveMutation.isPending}>
                      {saveMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      Save without notifying
                    </Button>
                    <Button
                      type="button"
                      onClick={() => submit(true)}
                      disabled={saveMutation.isPending}
                    >
                      {saveMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      Save and resend
                    </Button>
                  </>
                ) : (
                  <Button type="submit" disabled={saveMutation.isPending}>
                    {saveMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Save changes
                  </Button>
                )}
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
