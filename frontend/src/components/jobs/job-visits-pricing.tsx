"use client";

import { CalendarPlus, Check, Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  useCreateJobVisit,
  useDeleteJobVisit,
  useJobPricing,
  useJobVisits,
  useReplaceJobPricing,
  useUpdateJobVisit,
} from "@/hooks/useJobs";
import { localToIso } from "@/lib/jobs/job-derivations";

interface JobVisitsPricingProps {
  workspaceId: string;
  jobId: string;
  readOnly?: boolean;
}

interface EditableLineItem {
  key: string;
  name: string;
  quantity: string;
  unitPrice: string;
  taxable: boolean;
}

const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function formatVisitDate(value: string, anytime: boolean) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    ...(anytime ? {} : { timeStyle: "short" }),
  }).format(date);
}

function blankLineItem(): EditableLineItem {
  return { key: crypto.randomUUID(), name: "", quantity: "1", unitPrice: "0.00", taxable: true };
}

export function JobVisitsPricing({ workspaceId, jobId, readOnly = false }: JobVisitsPricingProps) {
  const visitsQuery = useJobVisits(workspaceId, jobId);
  const pricingQuery = useJobPricing(workspaceId, jobId, !readOnly);
  const createVisit = useCreateJobVisit(workspaceId, jobId);
  const updateVisit = useUpdateJobVisit(workspaceId, jobId);
  const deleteVisit = useDeleteJobVisit(workspaceId, jobId);
  const replacePricing = useReplaceJobPricing(workspaceId, jobId);

  const [showVisitForm, setShowVisitForm] = useState(false);
  const [visitStart, setVisitStart] = useState("");
  const [visitEnd, setVisitEnd] = useState("");
  const [visitAnytime, setVisitAnytime] = useState(false);
  const [visitInstructions, setVisitInstructions] = useState("");
  const [lineItems, setLineItems] = useState<EditableLineItem[] | null>(null);
  const [taxRate, setTaxRate] = useState<string | null>(null);
  const savedLineItems: EditableLineItem[] =
    pricingQuery.data?.items.map((item) => ({
      key: item.id,
      name: item.name,
      quantity: String(item.quantity),
      unitPrice: String(item.unit_price),
      taxable: item.taxable,
    })) ?? [];
  const displayedLineItems = lineItems ?? savedLineItems;
  const displayedTaxRate = taxRate ?? String(pricingQuery.data?.tax_rate ?? "0.00");
  const displayedSubtotal = displayedLineItems.reduce(
    (sum, item) => sum + Number(item.quantity || 0) * Number(item.unitPrice || 0),
    0,
  );
  const displayedTaxableSubtotal = displayedLineItems.reduce(
    (sum, item) =>
      sum + (item.taxable ? Number(item.quantity || 0) * Number(item.unitPrice || 0) : 0),
    0,
  );
  const displayedTax = displayedTaxableSubtotal * (Number(displayedTaxRate || 0) / 100);

  const addVisit = () => {
    const startsAt = localToIso(visitStart);
    const endsAt = localToIso(visitEnd);
    if (!startsAt || !endsAt) return;
    createVisit.mutate(
      {
        starts_at: startsAt,
        ends_at: endsAt,
        anytime: visitAnytime,
        instructions: visitInstructions.trim() || null,
      },
      {
        onSuccess: () => {
          toast.success("Visit added");
          setShowVisitForm(false);
          setVisitStart("");
          setVisitEnd("");
          setVisitInstructions("");
          setVisitAnytime(false);
        },
        onError: () => toast.error("Visit could not be added"),
      },
    );
  };

  const savePricing = () => {
    const validItems = displayedLineItems.filter((item) => item.name.trim());
    if (validItems.some((item) => Number(item.quantity) <= 0 || Number(item.unitPrice) < 0)) {
      toast.error("Quantity and price must be valid");
      return;
    }
    replacePricing.mutate(
      {
        tax_rate: Number(displayedTaxRate || 0),
        items: validItems.map((item) => ({
          name: item.name.trim(),
          description: null,
          quantity: Number(item.quantity),
          unit_price: Number(item.unitPrice),
          taxable: item.taxable,
        })),
      },
      {
        onSuccess: () => {
          setLineItems(null);
          setTaxRate(null);
          toast.success("Pricing saved");
        },
        onError: () => toast.error("Pricing could not be saved"),
      },
    );
  };

  return (
    <div className="space-y-6">
      <section aria-labelledby="job-visits-heading" className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 id="job-visits-heading" className="text-sm font-semibold">
              Visits
            </h3>
            <p className="text-xs text-muted-foreground">Schedule every trip for this job.</p>
          </div>
          {!readOnly && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setShowVisitForm((value) => !value)}
            >
              <CalendarPlus className="mr-2 size-4" /> Add visit
            </Button>
          )}
        </div>

        {showVisitForm && (
          <div className="space-y-3 rounded-md border p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="visit-start">Starts</Label>
                <Input
                  id="visit-start"
                  type="datetime-local"
                  value={visitStart}
                  onChange={(event) => setVisitStart(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="visit-end">Ends</Label>
                <Input
                  id="visit-end"
                  type="datetime-local"
                  value={visitEnd}
                  onChange={(event) => setVisitEnd(event.target.value)}
                />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="visit-anytime"
                checked={visitAnytime}
                onCheckedChange={(checked) => setVisitAnytime(checked === true)}
              />
              <Label htmlFor="visit-anytime" className="cursor-pointer font-normal">
                Anytime arrival
              </Label>
            </div>
            <Textarea
              value={visitInstructions}
              onChange={(event) => setVisitInstructions(event.target.value)}
              placeholder="Visit instructions"
              aria-label="Visit instructions"
              rows={2}
            />
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setShowVisitForm(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={addVisit}
                disabled={!visitStart || !visitEnd || createVisit.isPending}
              >
                {createVisit.isPending && <Loader2 className="mr-2 size-4 animate-spin" />} Save
                visit
              </Button>
            </div>
          </div>
        )}

        {visitsQuery.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : visitsQuery.isError ? (
          <p className="rounded-md border p-3 text-sm text-muted-foreground">
            Visits could not be loaded.
          </p>
        ) : visitsQuery.data.length === 0 ? (
          <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            No visits scheduled yet.
          </p>
        ) : (
          <div className="divide-y rounded-md border">
            {visitsQuery.data.map((visit) => (
              <div key={visit.id} className="flex items-start justify-between gap-3 p-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {formatVisitDate(visit.starts_at, visit.anytime)}
                  </p>
                  <p className="text-xs capitalize text-muted-foreground">
                    {visit.status.replaceAll("_", " ")}
                    {visit.anytime
                      ? " · Anytime"
                      : ` · until ${formatVisitDate(visit.ends_at, false)}`}
                  </p>
                  {visit.instructions && (
                    <p className="mt-1 text-sm text-muted-foreground">{visit.instructions}</p>
                  )}
                </div>
                {!readOnly && (
                  <div className="flex shrink-0 gap-1">
                    {visit.status !== "completed" && visit.status !== "cancelled" && (
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        aria-label="Complete visit"
                        onClick={() =>
                          updateVisit.mutate(
                            { visitId: visit.id, body: { status: "completed" } },
                            { onSuccess: () => toast.success("Visit completed") },
                          )
                        }
                      >
                        <Check className="size-4" />
                      </Button>
                    )}
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label="Delete visit"
                      onClick={() =>
                        deleteVisit.mutate(visit.id, {
                          onSuccess: () => toast.success("Visit deleted"),
                        })
                      }
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {!readOnly && (
        <section aria-labelledby="job-pricing-heading" className="space-y-3 border-t pt-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 id="job-pricing-heading" className="text-sm font-semibold">
                Products and services
              </h3>
              <p className="text-xs text-muted-foreground">Build the priced scope of work.</p>
            </div>
            {!pricingQuery.isError && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() =>
                  setLineItems((items) => [...(items ?? savedLineItems), blankLineItem()])
                }
              >
                <Plus className="mr-2 size-4" /> Add line
              </Button>
            )}
          </div>

          {pricingQuery.isPending ? (
            <Skeleton className="h-28 w-full" />
          ) : pricingQuery.isError ? (
            <p className="rounded-md border p-3 text-sm text-muted-foreground">
              Pricing is restricted to billing-authorized team members.
            </p>
          ) : (
            <>
              {displayedLineItems.length === 0 ? (
                <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                  No products or services added.
                </p>
              ) : (
                <div className="space-y-2">
                  {displayedLineItems.map((item, index) => (
                    <div
                      key={item.key}
                      className="grid grid-cols-[minmax(0,1fr)_70px_100px_28px_36px] items-center gap-2"
                    >
                      <Input
                        value={item.name}
                        onChange={(event) =>
                          setLineItems((items) =>
                            (items ?? savedLineItems).map((entry, itemIndex) =>
                              itemIndex === index ? { ...entry, name: event.target.value } : entry,
                            ),
                          )
                        }
                        placeholder="Product or service"
                        aria-label={`Line ${index + 1} name`}
                      />
                      <Input
                        type="number"
                        min="0.01"
                        step="0.01"
                        value={item.quantity}
                        onChange={(event) =>
                          setLineItems((items) =>
                            (items ?? savedLineItems).map((entry, itemIndex) =>
                              itemIndex === index
                                ? { ...entry, quantity: event.target.value }
                                : entry,
                            ),
                          )
                        }
                        aria-label={`Line ${index + 1} quantity`}
                      />
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        value={item.unitPrice}
                        onChange={(event) =>
                          setLineItems((items) =>
                            (items ?? savedLineItems).map((entry, itemIndex) =>
                              itemIndex === index
                                ? { ...entry, unitPrice: event.target.value }
                                : entry,
                            ),
                          )
                        }
                        aria-label={`Line ${index + 1} unit price`}
                      />
                      <Checkbox
                        checked={item.taxable}
                        aria-label={`Line ${index + 1} taxable`}
                        title="Taxable"
                        onCheckedChange={(checked) =>
                          setLineItems((items) =>
                            (items ?? savedLineItems).map((entry, itemIndex) =>
                              itemIndex === index ? { ...entry, taxable: checked === true } : entry,
                            ),
                          )
                        }
                      />
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        aria-label={`Remove line ${index + 1}`}
                        onClick={() =>
                          setLineItems((items) =>
                            (items ?? savedLineItems).filter((_, itemIndex) => itemIndex !== index),
                          )
                        }
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex flex-wrap items-end justify-between gap-3 rounded-md bg-muted/40 p-3">
                <div className="w-28 space-y-1.5">
                  <Label htmlFor="job-tax-rate">Tax rate (%)</Label>
                  <Input
                    id="job-tax-rate"
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={displayedTaxRate}
                    onChange={(event) => setTaxRate(event.target.value)}
                  />
                </div>
                <dl className="grid grid-cols-[auto_auto] gap-x-5 gap-y-1 text-sm text-right">
                  <dt className="text-muted-foreground">Subtotal</dt>
                  <dd>{currency.format(displayedSubtotal)}</dd>
                  <dt className="text-muted-foreground">Tax</dt>
                  <dd>{currency.format(displayedTax)}</dd>
                  <dt className="font-semibold">Total</dt>
                  <dd className="font-semibold">
                    {currency.format(displayedSubtotal + displayedTax)}
                  </dd>
                </dl>
              </div>
              <div className="flex justify-end">
                <Button
                  type="button"
                  size="sm"
                  onClick={savePricing}
                  disabled={replacePricing.isPending}
                >
                  {replacePricing.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}{" "}
                  Save pricing
                </Button>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
