"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { contactsApi } from "@/lib/api/contacts";
import { invoicesApi } from "@/lib/api/invoices";
import { describeInvoiceDelivery } from "@/lib/invoice-delivery";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Contact, Invoice, InvoiceSendResult } from "@/types";

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

const createInvoiceSchema = z.object({
  // Who gets billed. Required: an invoice with no bill-to contact can be marked
  // sent but can never be emailed to anyone, which is how invoices used to
  // silently go nowhere. Empty when the caller pre-fills the contact.
  contact_id: z.string(),
  due_date: z.string(),
  tax_amount: moneyString,
  notes: z.string(),
  line_items: z.array(lineItemSchema).min(1, { error: "Add at least one line item" }),
});

type CreateInvoiceFormValues = z.infer<typeof createInvoiceSchema>;

const EMPTY_LINE = { name: "", quantity: "1", unit_price: "" } as const;

/** "Sarah Henderson — sarah@example.com", degrading to whatever exists. */
function contactLabel(contact: Contact): string {
  const name =
    [contact.first_name, contact.last_name].filter(Boolean).join(" ").trim() ||
    `Contact #${contact.id}`;
  return contact.email ? `${name} — ${contact.email}` : name;
}

// True when the only line is the untouched starter row, so picking from the
// price book replaces it instead of leaving an empty line above the selection.
function isBlankLine(line: { name?: string; unit_price?: string }): boolean {
  return !line?.name?.trim() && !line?.unit_price?.trim();
}

const DEFAULT_VALUES: CreateInvoiceFormValues = {
  contact_id: "",
  due_date: "",
  tax_amount: "",
  notes: "",
  line_items: [{ ...EMPTY_LINE }],
};

interface InvoiceCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-fill the bill-to contact (e.g. from the contact quick action). */
  contactId?: number;
  onCreated?: (invoice: Invoice) => void;
}

export function InvoiceCreateDialog({
  open,
  onOpenChange,
  contactId,
  onCreated,
}: InvoiceCreateDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [contactSearch, setContactSearch] = useState("");
  // Only picked here when the caller didn't already know the customer.
  const needsContactPicker = contactId === undefined;

  const form = useForm<CreateInvoiceFormValues>({
    resolver: zodResolver(createInvoiceSchema),
    defaultValues: DEFAULT_VALUES,
  });

  // Server-side search keeps the picker usable past the endpoint's page cap:
  // the operator narrows by name/email instead of loading the whole roster.
  const contactsParams = {
    page: 1,
    page_size: 100,
    search: contactSearch.trim() || undefined,
  };
  const contactsQuery = useQuery({
    queryKey: queryKeys.contacts.list(workspaceId ?? "", contactsParams),
    queryFn: () => contactsApi.list(workspaceId ?? "", contactsParams),
    enabled: Boolean(workspaceId) && open && needsContactPicker,
  });
  const contacts = contactsQuery.data?.items ?? [];

  const selectedContactId = useWatch({
    control: form.control,
    name: "contact_id",
  });
  const selectedContact = contacts.find(
    (c) => String(c.id) === selectedContactId
  );
  // A contact with no email can be billed, but not *delivered* to. Say so
  // before the operator hits send rather than after.
  const selectedHasNoEmail = Boolean(selectedContact && !selectedContact.email);

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
      values: CreateInvoiceFormValues;
      send: boolean;
    }): Promise<Invoice | InvoiceSendResult> => {
      if (!workspaceId) throw new Error("No workspace selected");
      const { values, send } = input;
      const created = await invoicesApi.create(workspaceId, {
        contact_id: contactId ?? Number(values.contact_id),
        due_date: values.due_date || undefined,
        tax_amount: values.tax_amount === "" ? undefined : Number(values.tax_amount),
        notes: values.notes.trim() || undefined,
        line_items: values.line_items.map((li) => ({
          name: li.name.trim(),
          quantity: Number(li.quantity),
          unit_price: Number(li.unit_price),
        })),
      });
      if (send) {
        return invoicesApi.send(workspaceId, created.id);
      }
      return created;
    },
    onSuccess: (invoice, variables) => {
      if (variables.send) {
        // Report the real delivery outcome, not just that the row was created.
        const notice = describeInvoiceDelivery(invoice as InvoiceSendResult);
        if (notice.tone === "success") {
          toast.success(notice.message);
        } else {
          toast.warning(notice.message, { description: notice.description });
        }
      } else {
        toast.success(`Invoice ${invoice.number} created`);
      }
      if (workspaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.invoices.all(workspaceId),
        });
      }
      onCreated?.(invoice);
      setContactSearch("");
      onOpenChange(false);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to create invoice")),
  });

  const submit = (send: boolean) => {
    // Enforced here rather than in the zod schema because the field is only
    // required when the dialog is the one collecting it.
    if (needsContactPicker && !form.getValues("contact_id")) {
      form.setError("contact_id", {
        message: "Pick the customer this invoice bills",
      });
      return;
    }
    form.handleSubmit((values) => createMutation.mutate({ values, send }))();
  };

  const handleOpenChange = (next: boolean) => {
    if (!next && createMutation.isPending) return;
    // Clear the picker's search on close so the next open starts fresh.
    if (!next) setContactSearch("");
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New invoice</DialogTitle>
          <DialogDescription>
            Add line items and create a draft, or create and send it to the
            contact right away.
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
            {needsContactPicker && (
              <FormField
                control={form.control}
                name="contact_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Bill to</FormLabel>
                    <Input
                      placeholder="Search customers by name or email…"
                      value={contactSearch}
                      onChange={(event) => setContactSearch(event.target.value)}
                      className="mb-2"
                      disabled={createMutation.isPending}
                    />
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                      disabled={createMutation.isPending}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue
                            placeholder={
                              contactsQuery.isLoading
                                ? "Loading customers…"
                                : "Select a customer"
                            }
                          />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {contacts.length === 0 ? (
                          <div className="px-2 py-1.5 text-sm text-muted-foreground">
                            {contactsQuery.isLoading
                              ? "Loading customers…"
                              : "No customers found"}
                          </div>
                        ) : (
                          contacts.map((c: Contact) => (
                            <SelectItem key={c.id} value={String(c.id)}>
                              {contactLabel(c)}
                            </SelectItem>
                          ))
                        )}
                      </SelectContent>
                    </Select>
                    {selectedHasNoEmail && (
                      <p className="text-sm text-amber-600 dark:text-amber-500">
                        This customer has no email address, so the invoice can be
                        created but not sent. Add one on their contact record to
                        email it.
                      </p>
                    )}
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

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
