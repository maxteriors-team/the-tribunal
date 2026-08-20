"use client";

/**
 * Settings → Pricing: which services show a monthly-payment estimate.
 *
 * Financing presentation used to be lighting-only. It is now keyed by service
 * category: a category appears here to offer financing, and its minimum is the
 * project subtotal that qualifies — so a $9,000 roof gets a monthly figure and a
 * $400 gutter cleaning does not.
 *
 * Deliberately scoped to *presentation*. The margin knobs (`enabled`,
 * `fee_buffer`, terms, APR) are not editable here: `fee_buffer` grosses every
 * price up by `price / (1 - fee_buffer)` and cash pricing backs it out again, so
 * a mistyped value silently destroys margin on every financed job. Nothing on
 * this card can change what a customer is charged — only whether an estimate is
 * shown beside it. Saving PUTs the whole `financing` block back (the endpoint
 * replaces blocks wholesale), so every field this editor doesn't expose
 * round-trips untouched.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import type { FinancingConfig } from "@/types/sales-wizard";

// One editable eligibility row. `minimum` is held as a string so a half-typed
// value never snaps to 0 mid-edit; it's parsed and validated on save.
interface CategoryRow {
  /** Stable across renders so React keys survive typing in the name field. */
  id: string;
  category: string;
  minimum: string;
}

let rowSeq = 0;
const nextRowId = () => `financing-row-${(rowSeq += 1)}`;

function toRows(minimums: FinancingConfig["category_minimums"]): CategoryRow[] {
  return Object.entries(minimums ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, minimum]) => ({
      id: nextRowId(),
      category,
      minimum: String(minimum ?? 0),
    }));
}

export function FinancingSettingsCard() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: pricing, isPending } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(workspaceId!),
    enabled: !!workspaceId,
    // Shared with the other pricing editors by key (React Query dedupes the
    // fetch). Kept stable so a background refetch can't wipe unsaved edits —
    // this card writes the cache directly on save.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const [rows, setRows] = useState<CategoryRow[] | null>(null);
  const [disclaimer, setDisclaimer] = useState("");
  // Snapshot of the server block so save preserves the margin knobs and copy
  // this editor doesn't expose.
  const [serverFinancing, setServerFinancing] = useState<FinancingConfig | null>(null);

  if (pricing?.financing && pricing.financing !== serverFinancing) {
    setServerFinancing(pricing.financing);
    setRows(toRows(pricing.financing.category_minimums));
    setDisclaimer(pricing.financing.disclaimer ?? "");
  }

  const mutation = useSettingsSaveMutation({
    mutationFn: (financing: FinancingConfig) =>
      salesWizardApi.updatePricing(workspaceId!, { financing }),
    successMessage: "Financing presentation settings are up to date.",
    errorMessage:
      "We couldn't save financing presentation settings. Check your connection and try again.",
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.salesWizard.pricing(workspaceId ?? ""), updated);
    },
  });

  const disabled = mutation.isPending || !serverFinancing || !rows;

  const patchRow = (id: string, patch: Partial<CategoryRow>) =>
    setRows((prev) =>
      prev ? prev.map((row) => (row.id === id ? { ...row, ...patch } : row)) : prev,
    );

  const addRow = () =>
    setRows((prev) => [...(prev ?? []), { id: nextRowId(), category: "", minimum: "0" }]);

  const removeRow = (id: string) =>
    setRows((prev) => (prev ? prev.filter((row) => row.id !== id) : prev));

  const save = () => {
    if (!serverFinancing || !rows) return;

    const minimums: Record<string, number> = {};
    for (const row of rows) {
      // The server normalizes keys the same way, so match it here to catch a
      // duplicate before one row silently overwrites another.
      const category = row.category.trim().toLowerCase();
      if (!category) {
        toast.error("Give every service a name, or remove the empty row");
        return;
      }
      if (category in minimums) {
        toast.error(`"${category}" is listed twice`);
        return;
      }
      const minimum = Number.parseFloat(row.minimum);
      if (!Number.isFinite(minimum) || minimum < 0) {
        toast.error(`Minimum for "${category}" must be a number ≥ 0`);
        return;
      }
      minimums[category] = minimum;
    }

    // Spread the server snapshot first so the margin knobs and unexposed copy
    // survive the block-replace save; then apply the edited values. A blank
    // disclaimer saves as null, which the server renders as its standard
    // disclaimer — a payment figure can never appear without one.
    mutation.mutate({
      ...serverFinancing,
      category_minimums: minimums,
      disclaimer: disclaimer.trim() || null,
    });
  };

  if (isPending || !rows) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1.5">
          <CardTitle>Financing Presentation</CardTitle>
          <CardDescription>
            Which services show an estimated monthly payment beside the price, and the project
            subtotal that qualifies. A service that isn&rsquo;t listed never shows a payment
            estimate. Use the name your price book uses for the service — roofing, siding, gutters,
            landscape.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-3">
          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No services offer financing. Add one to start showing monthly payment estimates.
            </p>
          ) : (
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.25rem] items-end gap-2 text-sm font-medium sm:flex sm:gap-3">
              <div className="min-w-0 flex-1">Service</div>
              <div className="min-w-0 sm:w-40">Minimum ($)</div>
              {/* Spacer matching the per-row remove button. */}
              <div className="size-9" aria-hidden="true" />
            </div>
          )}

          {rows.map((row, index) => (
            <div
              key={row.id}
              className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.25rem] items-end gap-2 sm:flex sm:gap-3"
            >
              <Input
                className="min-w-0 flex-1"
                aria-label={`Service ${index + 1} name`}
                value={row.category}
                placeholder="roofing"
                onChange={(e) => patchRow(row.id, { category: e.target.value })}
                disabled={disabled}
              />
              <Input
                className="min-w-0 sm:w-40"
                aria-label={`Service ${index + 1} minimum ($)`}
                type="number"
                min={0}
                step="0.01"
                inputMode="decimal"
                value={row.minimum}
                onChange={(e) => patchRow(row.id, { minimum: e.target.value })}
                disabled={disabled}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove service ${index + 1}`}
                onClick={() => removeRow(row.id)}
                disabled={disabled}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}

          <Button type="button" variant="outline" size="sm" onClick={addRow} disabled={disabled}>
            <Plus className="size-4" /> Add service
          </Button>
          <p className="text-xs text-muted-foreground">
            0 means any job qualifies. Set a floor to keep small jobs from showing a payment
            estimate.
          </p>
        </div>

        <Separator />

        <div className="space-y-2">
          <Label htmlFor="financing-disclaimer">Estimate disclaimer</Label>
          <Textarea
            id="financing-disclaimer"
            rows={3}
            value={disclaimer}
            onChange={(e) => setDisclaimer(e.target.value)}
            disabled={disabled}
          />
          <p className="text-xs text-muted-foreground">
            Shown with every payment figure. Payments are estimates, never an approved offer. Leave
            this blank to use the standard disclaimer — it can&rsquo;t be removed.
          </p>
        </div>

        <Separator />

        <div className="flex justify-end">
          <Button className="w-full sm:w-auto" type="button" onClick={save} disabled={disabled}>
            {mutation.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Saving…
              </>
            ) : (
              "Save financing settings"
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
