"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

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
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { quotesApi } from "@/lib/api/quotes";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Quote, UpdateQuoteRequest } from "@/types";

const moneyString = z
  .string()
  .trim()
  .refine((v) => v === "" || (!Number.isNaN(Number(v)) && Number(v) >= 0), {
    error: "Enter a valid amount",
  });

const editQuoteSchema = z
  .object({
    title: z.string().trim().max(200, { error: "Keep the title under 200 characters" }),
    issue_date: z.string(),
    expiry_date: z.string(),
    tax_amount: moneyString,
    discount_amount: moneyString,
    deposit_mode: z.enum(["none", "percentage", "fixed"]),
    deposit_value: moneyString,
    notes: z.string(),
    terms: z.string(),
  })
  .refine(
    (v) =>
      v.deposit_mode !== "percentage" ||
      (v.deposit_value !== "" && Number(v.deposit_value) <= 100),
    { error: "Enter a percentage between 0 and 100", path: ["deposit_value"] },
  )
  .refine((v) => v.deposit_mode !== "fixed" || v.deposit_value !== "", {
    error: "Enter the deposit amount",
    path: ["deposit_value"],
  })
  .refine(
    (v) => !v.issue_date || !v.expiry_date || v.expiry_date >= v.issue_date,
    { error: "Valid-until can't be before the issue date", path: ["expiry_date"] },
  );

type EditQuoteFormValues = z.infer<typeof editQuoteSchema>;

interface QuoteEditDialogProps {
  quote: Pick<Quote, "id" | "status" | "total" | "number" | "currency"> | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Edit a quote's header — including after it has been sent.
 *
 * A sent quote is not frozen: the customer holds a live proposal link, and the
 * public page reads title, dates, notes, terms and the deposit straight off the
 * quote row on every load. So saving here changes what the customer sees at the
 * link they already have, with no re-send. The description says so, because an
 * operator fixing a typo and an operator moving a deposit are doing very
 * different things to a live document.
 *
 * What this dialog deliberately does NOT do is reprice. Tax and discount are
 * offered only on a *plain* quote, whose line items are its price. A sales-
 * wizard quote keeps its money in `proposal_document` and the client picks a
 * package from it; editing tax there would move the dashboard total while the
 * customer's page kept showing the document's — a divergence nobody would see
 * until the invoice didn't match. Repricing a wizard quote goes through the
 * wizard, not a header form.
 */
export function QuoteEditDialog({
  quote,
  open,
  onOpenChange,
}: QuoteEditDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  // The list row is a summary: it carries no `proposal_document`, which is the
  // one field that decides whether repricing fields are safe to show.
  const detailQuery = useQuery({
    queryKey: queryKeys.quotes.detail(workspaceId ?? "", quote?.id ?? ""),
    queryFn: () => quotesApi.get(workspaceId ?? "", quote?.id ?? ""),
    enabled: Boolean(workspaceId) && Boolean(quote?.id) && open,
  });
  const detail = detailQuery.data;

  const isWizardQuote = Boolean(detail?.proposal_document);
  const alreadySent = quote?.status === "sent";

  const form = useForm<EditQuoteFormValues>({
    resolver: zodResolver(editQuoteSchema),
    defaultValues: {
      title: "",
      issue_date: "",
      expiry_date: "",
      tax_amount: "",
      discount_amount: "",
      deposit_mode: "none",
      deposit_value: "",
      notes: "",
      terms: "",
    },
  });

  // Populate once the detail lands (and on reopen for a different quote).
  useEffect(() => {
    if (!open || !detail) return;
    const depositMode =
      detail.deposit_amount_fixed != null && detail.deposit_amount_fixed > 0
        ? "fixed"
        : detail.deposit_percentage != null && detail.deposit_percentage > 0
          ? "percentage"
          : "none";
    form.reset({
      title: detail.title ?? "",
      issue_date: detail.issue_date ?? "",
      expiry_date: detail.expiry_date ?? "",
      tax_amount: detail.tax_amount ? String(detail.tax_amount) : "",
      discount_amount: detail.discount_amount ? String(detail.discount_amount) : "",
      deposit_mode: depositMode,
      deposit_value:
        depositMode === "fixed"
          ? String(detail.deposit_amount_fixed)
          : depositMode === "percentage"
            ? String(detail.deposit_percentage)
            : "",
      notes: detail.notes ?? "",
      terms: detail.terms ?? "",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, detail?.id, detail?.updated_at]);

  const saveMutation = useMutation({
    mutationFn: async (values: EditQuoteFormValues): Promise<Quote> => {
      if (!workspaceId || !quote) throw new Error("No quote selected");

      const payload: UpdateQuoteRequest = {
        // The API skips null/absent fields, so an emptied text box is sent as
        // "" to actually clear it. An emptied date can't be cleared that way
        // ("" is not a date), so it is omitted and keeps its stored value.
        title: values.title,
        notes: values.notes,
        terms: values.terms,
        ...(values.issue_date ? { issue_date: values.issue_date } : {}),
        ...(values.expiry_date ? { expiry_date: values.expiry_date } : {}),
        // Only a plain quote prices from its line items, so only a plain quote
        // may move tax/discount. See the class comment.
        ...(isWizardQuote
          ? {}
          : {
              tax_amount: values.tax_amount ? Number(values.tax_amount) : 0,
              discount_amount: values.discount_amount
                ? Number(values.discount_amount)
                : 0,
            }),
        // The two deposit columns are mutually exclusive server-side (setting
        // one clears the other), and null means "leave it alone" rather than
        // "remove it" — so clearing a deposit is expressed as 0%, which the
        // server's own `deposit_amount` reads as no deposit at all.
        ...(values.deposit_mode === "fixed"
          ? { deposit_amount_fixed: Number(values.deposit_value) }
          : {
              deposit_percentage:
                values.deposit_mode === "percentage"
                  ? Number(values.deposit_value)
                  : 0,
            }),
      };

      return quotesApi.update(workspaceId, quote.id, payload);
    },
    onSuccess: (updated) => {
      toast.success(`Quote ${updated.number} updated`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.quotes.all(workspaceId ?? ""),
      });
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Could not update the quote"));
    },
  });

  const depositMode = useWatch({ control: form.control, name: "deposit_mode" });
  const depositValue = useWatch({ control: form.control, name: "deposit_value" });
  const total = detail?.total ?? quote?.total ?? 0;
  const depositPreview =
    depositMode === "percentage"
      ? (total * (Number(depositValue) || 0)) / 100
      : depositMode === "fixed"
        ? Math.min(Number(depositValue) || 0, total)
        : null;

  const handleOpenChange = (next: boolean) => {
    if (!next && saveMutation.isPending) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit quote {quote?.number ?? ""}</DialogTitle>
          <DialogDescription>
            {alreadySent
              ? "This quote has already gone out. Saving updates the proposal at the link the customer already has — they don't need a new one."
              : "Update this draft before it goes out."}
          </DialogDescription>
        </DialogHeader>

        {detailQuery.isLoading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : detailQuery.isError ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Could not load this quote. Close and try again.
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
              <FormField
                control={form.control}
                name="title"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Title</FormLabel>
                    <FormControl>
                      <Input placeholder="What this quote is for" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-2 gap-3">
                <FormField
                  control={form.control}
                  name="issue_date"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Issue date</FormLabel>
                      <FormControl>
                        <Input type="date" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="expiry_date"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Valid until</FormLabel>
                      <FormControl>
                        <Input type="date" {...field} />
                      </FormControl>
                      {/* The reason most sent quotes get edited: the customer
                          needs another week and the price shouldn't lapse. */}
                      <FormDescription>
                        Push this out to keep a sent quote from expiring.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {!isWizardQuote && (
                <div className="grid grid-cols-2 gap-3">
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
                        <FormLabel>Discount</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min="0"
                            step="0.01"
                            inputMode="decimal"
                            placeholder="0.00"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <FormField
                  control={form.control}
                  name="deposit_mode"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Deposit</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="none">No deposit</SelectItem>
                          <SelectItem value="percentage">
                            Percentage of total
                          </SelectItem>
                          <SelectItem value="fixed">Fixed amount</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                {depositMode !== "none" && (
                  <FormField
                    control={form.control}
                    name="deposit_value"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          {depositMode === "percentage" ? "Percent" : "Amount"}
                        </FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min="0"
                            max={depositMode === "percentage" ? "100" : undefined}
                            step="0.01"
                            inputMode="decimal"
                            placeholder={
                              depositMode === "percentage" ? "25" : "0.00"
                            }
                            {...field}
                          />
                        </FormControl>
                        {depositPreview != null && (
                          <FormDescription>
                            Due today: {formatCurrency(depositPreview, quote?.currency)}
                          </FormDescription>
                        )}
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
              </div>

              {/* A paid deposit is money already taken. Changing the deposit
                  now doesn't refund or re-charge anything, so say that plainly
                  rather than letting the operator assume it does. */}
              {detail?.deposit_paid_at && (
                <p className="text-sm text-muted-foreground">
                  This customer already paid their deposit. Changing it here
                  won&rsquo;t refund or charge the difference.
                </p>
              )}

              <FormField
                control={form.control}
                name="notes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Notes</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Optional note shown on the proposal..."
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
                        placeholder="Terms shown on the proposal..."
                        className="min-h-[60px]"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {isWizardQuote && (
                <p className="border-t pt-3 text-sm text-muted-foreground">
                  Pricing on this proposal comes from the sales wizard, so it
                  isn&rsquo;t editable here. Rebuild the quote in the wizard to
                  change what the packages cost.
                </p>
              )}

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
