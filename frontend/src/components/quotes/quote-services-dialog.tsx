"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { quotesApi } from "@/lib/api/quotes";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Quote } from "@/types";

interface QuoteServicesDialogProps {
  workspaceId: string;
  quote: Quote | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Add, edit, or remove services on a quote that already exists.
 *
 * The server projects a rich proposal's add-on charges and a plain quote's line
 * items into the same service list. Only plain line items expose Edit: proposal
 * fixture lines stay server-priced and must be changed in their originating
 * designer.
 *
 * Every mutation returns the repriced quote, so the total shown here is the
 * server's own number rather than a local sum that could disagree with it.
 */
export function QuoteServicesDialog({
  workspaceId,
  quote,
  open,
  onOpenChange,
}: QuoteServicesDialogProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [catalogItemId, setCatalogItemId] = useState<string | null>(null);
  const [editingLineItemId, setEditingLineItemId] = useState<string | null>(null);

  // The list row carries no services, so fetch the detail when opening.
  const detailQuery = useQuery({
    queryKey: queryKeys.quotes.detail(workspaceId, quote?.id ?? ""),
    queryFn: () => quotesApi.get(workspaceId, quote?.id ?? ""),
    enabled: Boolean(workspaceId) && Boolean(quote?.id) && open,
  });
  const detail = detailQuery.data;
  const services = detail?.services ?? [];
  const isWizardQuote = Boolean(detail?.is_wizard_quote);
  const lineItemsById = new Map(
    isWizardQuote ? [] : (detail?.line_items ?? []).map((lineItem) => [lineItem.id, lineItem]),
  );
  const editingLineItem = editingLineItemId ? lineItemsById.get(editingLineItemId) : undefined;

  const resetDraft = () => {
    setName("");
    setDescription("");
    setAmount("");
    setCatalogItemId(null);
    setEditingLineItemId(null);
  };

  const draftKey = open ? (quote?.id ?? null) : null;
  const [loadedDraftKey, setLoadedDraftKey] = useState(draftKey);
  if (loadedDraftKey !== draftKey) {
    setLoadedDraftKey(draftKey);
    if (draftKey) {
      setName("");
      setDescription("");
      setAmount("");
      setCatalogItemId(null);
      setEditingLineItemId(null);
    }
  }

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.quotes.all(workspaceId),
    });
  };

  const addMutation = useMutation({
    mutationFn: async (): Promise<Quote> => {
      if (!quote) throw new Error("No quote selected");
      return quotesApi.addService(workspaceId, quote.id, {
        name: name.trim(),
        amount: Number(amount),
        ...(catalogItemId ? { catalog_item_id: catalogItemId } : {}),
      });
    },
    onSuccess: (updated) => {
      toast.success(`Added to ${updated.number}`);
      resetDraft();
      invalidate();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't add that service")),
  });

  const updateMutation = useMutation({
    mutationFn: async (): Promise<Quote> => {
      if (!quote || !editingLineItem) throw new Error("No line item selected");
      const quantity = Number(editingLineItem.quantity);
      const discount = Number(editingLineItem.discount);
      if (!Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(discount)) {
        throw new Error("This line item has invalid quantity or discount math");
      }
      return quotesApi.updateLineItem(workspaceId, quote.id, editingLineItem.id, {
        name: name.trim(),
        description: description.trim(),
        // The operator edits the overall line total. Solve for unit price while
        // leaving the original quantity and discount untouched.
        unit_price: (Number(amount) + discount) / quantity,
      });
    },
    onSuccess: () => {
      toast.success("Service updated");
      resetDraft();
      invalidate();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't update that service")),
  });

  const removeMutation = useMutation({
    mutationFn: async (serviceId: string): Promise<Quote> => {
      if (!quote) throw new Error("No quote selected");
      return quotesApi.removeService(workspaceId, quote.id, serviceId);
    },
    onSuccess: () => {
      toast.success("Service removed");
      invalidate();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't remove that service")),
  });

  const busy = addMutation.isPending || updateMutation.isPending || removeMutation.isPending;
  const parsedAmount = Number(amount);
  const validDraft =
    name.trim().length > 0 && amount.trim().length > 0 && Number.isFinite(parsedAmount) && !busy;
  const canAdd = validDraft && parsedAmount > 0;
  const canUpdate =
    validDraft &&
    parsedAmount >= 0 &&
    Boolean(editingLineItem && Number(editingLineItem.quantity) > 0);

  const beginEdit = (
    serviceId: string,
    serviceName: string,
    serviceDescription: string | null | undefined,
    serviceAmount: number,
  ) => {
    const lineItem = lineItemsById.get(serviceId);
    if (!lineItem || Number(lineItem.quantity) <= 0) return;
    setEditingLineItemId(lineItem.id);
    setName(serviceName);
    setDescription(serviceDescription ?? "");
    setAmount(String(serviceAmount));
    setCatalogItemId(null);
  };

  // Already in the customer's hands, on a link that reprices the moment this
  // saves. Worth saying out loud rather than letting a rep discover it.
  const alreadySent = quote?.status === "sent";

  const handleOpenChange = (next: boolean) => {
    if (!next && busy) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Quote services{quote?.number ? ` for ${quote.number}` : ""}</DialogTitle>
          <DialogDescription>
            {alreadySent
              ? "This quote has already been sent. Editing or adding a service updates what the customer sees on their proposal link."
              : "Add or edit work on this quote. The total updates as you go."}
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
          <div className="space-y-5 py-4">
            <div className="space-y-2">
              {services.length === 0 ? (
                <p className="rounded-md border border-dashed py-6 text-center text-sm text-muted-foreground">
                  No services added yet.
                </p>
              ) : (
                services.map((service) => {
                  const lineItem = lineItemsById.get(service.id);
                  const invalidQuantity = lineItem && Number(lineItem.quantity) <= 0;
                  return (
                    <div
                      key={service.id}
                      className="flex items-center gap-3 rounded-md border px-3 py-2"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{service.name}</div>
                        {service.description && (
                          <div className="truncate text-xs text-muted-foreground">
                            {service.description}
                          </div>
                        )}
                      </div>
                      <div className="shrink-0 text-sm tabular-nums">
                        {formatCurrency(service.amount, detail?.currency)}
                      </div>
                      {lineItem && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            beginEdit(service.id, service.name, service.description, service.amount)
                          }
                          disabled={busy || invalidQuantity}
                          title={
                            invalidQuantity
                              ? "A line with zero quantity cannot be edited"
                              : undefined
                          }
                          aria-label={`Edit ${service.name}`}
                        >
                          <Pencil className="mr-1.5 h-3.5 w-3.5" />
                          Edit
                        </Button>
                      )}
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => removeMutation.mutate(service.id)}
                        disabled={busy}
                        aria-label={`Remove ${service.name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  );
                })
              )}
            </div>

            <div className="space-y-3 border-t pt-4">
              <div className="flex items-center justify-between">
                <Label htmlFor="quote-service-name">
                  {editingLineItem ? "Edit service" : "Add a service"}
                </Label>
                {!editingLineItem && (
                  <CatalogPicker
                    disabled={busy}
                    onPick={(item) => {
                      setName(item.name);
                      setAmount(String(item.unit_price));
                      setCatalogItemId(item.id);
                    }}
                  />
                )}
              </div>
              <div className="grid grid-cols-[1fr_8rem] gap-2">
                <Input
                  id="quote-service-name"
                  placeholder="e.g. Gutter cleaning"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    // The price-book link only holds while the picked item is
                    // still what's in the box; hand-editing makes it a custom
                    // service, and keeping the id would credit the attach to a
                    // catalog item the rep no longer chose.
                    setCatalogItemId(null);
                  }}
                  disabled={busy}
                />
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  inputMode="decimal"
                  placeholder="Amount"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  disabled={busy}
                  aria-label={editingLineItem ? "Overall amount" : "Amount"}
                />
              </div>
              {editingLineItem && (
                <div className="space-y-1.5">
                  <Label htmlFor="quote-service-description">Description</Label>
                  <Input
                    id="quote-service-description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Optional details"
                    disabled={busy}
                  />
                </div>
              )}
              {isWizardQuote && (
                // On a wizard quote the server grosses the amount up by the
                // finance buffer, so the figure that lands in the list above is
                // not the one typed here. Saying so beats a rep entering $850
                // and quietly reading it back as $920.
                <p className="text-xs text-muted-foreground">
                  Enter the amount you keep — the finance fee is added automatically for a rich
                  proposal.
                </p>
              )}
              <div className="flex gap-2">
                {editingLineItem && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={resetDraft}
                    disabled={busy}
                  >
                    Cancel
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => (editingLineItem ? updateMutation.mutate() : addMutation.mutate())}
                  disabled={editingLineItem ? !canUpdate : !canAdd}
                  className="flex-1"
                >
                  {addMutation.isPending || updateMutation.isPending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : editingLineItem ? (
                    <Pencil className="mr-1.5 h-3.5 w-3.5" />
                  ) : (
                    <Plus className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {editingLineItem ? "Save changes" : "Add to quote"}
                </Button>
              </div>
            </div>

            <div className="flex items-center justify-between border-t pt-3 text-sm">
              <span className="text-muted-foreground">Quote total</span>
              <span className="text-base font-semibold">
                {formatCurrency(detail?.total ?? 0, detail?.currency)}
              </span>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button type="button" onClick={() => handleOpenChange(false)} disabled={busy}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
