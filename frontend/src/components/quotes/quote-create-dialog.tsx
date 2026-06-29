"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
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
import { quotesApi } from "@/lib/api/quotes";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Quote } from "@/types";

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
  unit_price: moneyString.refine((v) => v !== "", { error: "Required" }),
});

const createQuoteSchema = z.object({
  title: z.string(),
  expiry_date: z.string(),
  tax_amount: moneyString,
  notes: z.string(),
  line_items: z.array(lineItemSchema).min(1, { error: "Add at least one line item" }),
});

type CreateQuoteFormValues = z.infer<typeof createQuoteSchema>;

const EMPTY_LINE = { name: "", quantity: "1", unit_price: "" } as const;

// True when the only line is the untouched starter row, so picking from the
// price book replaces it instead of leaving an empty line above the selection.
function isBlankLine(line: { name?: string; unit_price?: string }): boolean {
  return !line?.name?.trim() && !line?.unit_price?.trim();
}

const DEFAULT_VALUES: CreateQuoteFormValues = {
  title: "",
  expiry_date: "",
  tax_amount: "",
  notes: "",
  line_items: [{ ...EMPTY_LINE }],
};

interface QuoteCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-fill the quote-to contact (e.g. from the contact quick action). */
  contactId?: number;
  onCreated?: (quote: Quote) => void;
}

export function QuoteCreateDialog({
  open,
  onOpenChange,
  contactId,
  onCreated,
}: QuoteCreateDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const form = useForm<CreateQuoteFormValues>({
    resolver: zodResolver(createQuoteSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "line_items",
  });

  useEffect(() => {
    if (open) form.reset(DEFAULT_VALUES);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Live total preview from the current form values. useWatch (not form.watch)
  // is the memoizable API the React Compiler accepts.
  const watchedLines = useWatch({ control: form.control, name: "line_items" });
  const watchedTax = useWatch({ control: form.control, name: "tax_amount" });
  const subtotal = (watchedLines ?? []).reduce((sum, li) => {
    const qty = Number(li?.quantity) || 0;
    const price = Number(li?.unit_price) || 0;
    return sum + qty * price;
  }, 0);
  const tax = Number(watchedTax) || 0;
  const total = subtotal + tax;

  const createMutation = useMutation({
    mutationFn: async (input: {
      values: CreateQuoteFormValues;
      send: boolean;
    }): Promise<Quote> => {
      if (!workspaceId) throw new Error("No workspace selected");
      const { values, send } = input;
      const created = await quotesApi.create(workspaceId, {
        contact_id: contactId,
        title: values.title.trim() || undefined,
        expiry_date: values.expiry_date || undefined,
        tax_amount: values.tax_amount === "" ? undefined : Number(values.tax_amount),
        notes: values.notes.trim() || undefined,
        line_items: values.line_items.map((li) => ({
          name: li.name.trim(),
          quantity: Number(li.quantity),
          unit_price: Number(li.unit_price),
        })),
      });
      if (send) {
        return quotesApi.send(workspaceId, created.id);
      }
      return created;
    },
    onSuccess: (quote, variables) => {
      toast.success(
        variables.send
          ? `Quote ${quote.number} sent`
          : `Quote ${quote.number} created`
      );
      if (workspaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.quotes.all(workspaceId),
        });
      }
      onCreated?.(quote);
      onOpenChange(false);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to create quote")),
  });

  const submit = (send: boolean) =>
    form.handleSubmit((values) => createMutation.mutate({ values, send }))();

  const handleOpenChange = (next: boolean) => {
    if (!next && createMutation.isPending) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New quote</DialogTitle>
          <DialogDescription>
            Add line items and create a draft, or create and send the estimate to
            the contact right away.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(false);
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
                    <Input placeholder="e.g. Backyard lighting install" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <FormLabel>Line items</FormLabel>
                <div className="flex items-center gap-2">
                  <CatalogPicker
                    disabled={createMutation.isPending}
                    onPick={(item) => {
                      const line = {
                        name: item.name,
                        quantity: "1",
                        unit_price: String(item.unit_price),
                      };
                      const current = form.getValues("line_items");
                      if (current.length === 1 && isBlankLine(current[0])) {
                        // Replace the untouched starter row.
                        form.setValue("line_items.0", line, {
                          shouldValidate: true,
                        });
                      } else {
                        append(line);
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => append({ ...EMPTY_LINE })}
                  >
                    <Plus className="mr-1 h-3.5 w-3.5" />
                    Add line
                  </Button>
                </div>
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
                          <Input placeholder="Description" {...f} />
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
                    onClick={() => (fields.length > 1 ? remove(index) : undefined)}
                    disabled={fields.length <= 1}
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
                name="expiry_date"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Valid until</FormLabel>
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
                      placeholder="Optional note shown on the quote..."
                      className="min-h-[60px]"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="flex items-center justify-between border-t pt-3 text-sm">
              <span className="text-muted-foreground">Total</span>
              <span className="text-base font-semibold">
                {formatCurrency(total)}
              </span>
            </div>

            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={createMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="outline"
                disabled={createMutation.isPending}
              >
                {createMutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Save draft
              </Button>
              <Button
                type="button"
                onClick={() => submit(true)}
                disabled={createMutation.isPending}
              >
                {createMutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Create &amp; send
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
