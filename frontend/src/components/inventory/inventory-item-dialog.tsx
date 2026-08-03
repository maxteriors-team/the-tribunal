"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { inventoryApi } from "@/lib/api/inventory";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { InventoryItem } from "@/types/inventory";

interface InventoryItemDialogProps {
  workspaceId: string;
  /** When present the dialog edits this item; otherwise it creates one. */
  item?: InventoryItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface FormState {
  name: string;
  sku: string;
  unit_of_measure: string;
  reorder_point: string;
  reorder_quantity: string;
  safety_stock: string;
  lead_time_days: string;
  supplier_name: string;
  supplier_sku: string;
  notes: string;
  is_active: boolean;
}

const EMPTY: FormState = {
  name: "",
  sku: "",
  unit_of_measure: "each",
  reorder_point: "",
  reorder_quantity: "",
  safety_stock: "",
  lead_time_days: "",
  supplier_name: "",
  supplier_sku: "",
  notes: "",
  is_active: true,
};

/** Blank stays blank: an empty threshold means "not managed", not zero. */
function toNumberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function InventoryItemDialog({
  workspaceId,
  item,
  open,
  onOpenChange,
}: InventoryItemDialogProps) {
  const queryClient = useQueryClient();
  const isEdit = Boolean(item);
  const [values, setValues] = useState<FormState>(EMPTY);

  useEffect(() => {
    if (!open) return;
    setValues(
      item
        ? {
            name: item.name,
            sku: item.sku ?? "",
            unit_of_measure: item.unit_of_measure,
            reorder_point:
              item.reorder_point === null || item.reorder_point === undefined
                ? ""
                : String(item.reorder_point),
            reorder_quantity:
              item.reorder_quantity === null || item.reorder_quantity === undefined
                ? ""
                : String(item.reorder_quantity),
            safety_stock: String(item.safety_stock ?? 0),
            lead_time_days:
              item.lead_time_days === null || item.lead_time_days === undefined
                ? ""
                : String(item.lead_time_days),
            supplier_name: item.supplier_name ?? "",
            supplier_sku: item.supplier_sku ?? "",
            notes: item.notes ?? "",
            is_active: item.is_active,
          }
        : EMPTY,
    );
  }, [open, item]);

  // The suggestion is advisory. It is shown next to the operator's own number
  // and applied only when they click — a threshold that silently retunes itself
  // is a threshold nobody trusts.
  const suggestion = useQuery({
    queryKey: queryKeys.inventory.reorderSuggestion(workspaceId, item?.id ?? ""),
    queryFn: () => inventoryApi.reorderSuggestion(workspaceId, item!.id),
    enabled: open && Boolean(workspaceId) && Boolean(item),
  });

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setValues((previous) => ({ ...previous, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: values.name.trim(),
        sku: values.sku.trim() || null,
        unit_of_measure: values.unit_of_measure.trim() || "each",
        // Only weighted-average costing is implemented; the field exists so
        // FIFO can be added later without a data migration.
        valuation_method: "weighted_average" as const,
        reorder_point: toNumberOrNull(values.reorder_point),
        reorder_quantity: toNumberOrNull(values.reorder_quantity),
        safety_stock: toNumberOrNull(values.safety_stock) ?? 0,
        lead_time_days: toNumberOrNull(values.lead_time_days),
        supplier_name: values.supplier_name.trim() || null,
        supplier_sku: values.supplier_sku.trim() || null,
        notes: values.notes.trim() || null,
        is_active: values.is_active,
      };
      return item
        ? inventoryApi.updateItem(workspaceId, item.id, payload)
        : inventoryApi.createItem(workspaceId, payload);
    },
    onSuccess: (saved) => {
      toast.success(isEdit ? `Updated ${saved.name}` : `Tracking ${saved.name}`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.inventory.all(workspaceId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.inventory.reorderReport(workspaceId),
      });
      onOpenChange(false);
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Failed to save item")),
  });

  // The service computes to 4 decimals; a threshold an operator reads and
  // retypes only needs 2, and "5.93" is a number they can sanity-check.
  const rawSuggestion = suggestion.data?.suggested_reorder_point;
  const suggested =
    rawSuggestion === null || rawSuggestion === undefined
      ? null
      : Math.round(rawSuggestion * 100) / 100;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && save.isPending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${item?.name}` : "Track a new item"}</DialogTitle>
          <DialogDescription>
            Stock arrives through a receipt, so quantities are not set here. Set
            a reorder point to have this item raise a low-stock alert.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="item-name">Name</Label>
              <Input
                id="item-name"
                required
                placeholder="e.g. Sodium hypochlorite 12.5%"
                value={values.name}
                onChange={(event) => set("name", event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="item-sku">SKU</Label>
              <Input
                id="item-sku"
                placeholder="Optional"
                value={values.sku}
                onChange={(event) => set("sku", event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="item-uom">Unit</Label>
              <Input
                id="item-uom"
                placeholder="each, gallon, ft"
                value={values.unit_of_measure}
                onChange={(event) => set("unit_of_measure", event.target.value)}
              />
            </div>
          </div>

          <fieldset className="space-y-3 rounded-lg border p-3">
            <legend className="px-1 text-sm font-medium">Reordering</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="item-reorder-point">Reorder point</Label>
                <Input
                  id="item-reorder-point"
                  type="number"
                  min="0"
                  step="0.0001"
                  inputMode="decimal"
                  placeholder="Leave blank to skip alerts"
                  value={values.reorder_point}
                  onChange={(event) => set("reorder_point", event.target.value)}
                  aria-describedby="item-reorder-point-hint"
                />
                <p
                  id="item-reorder-point-hint"
                  className="text-xs text-muted-foreground"
                >
                  {suggested !== null ? (
                    <>
                      Recent usage suggests {suggested}.{" "}
                      <button
                        type="button"
                        className="font-medium underline underline-offset-2 hover:no-underline"
                        onClick={() => set("reorder_point", String(suggested))}
                      >
                        Use this
                      </button>
                    </>
                  ) : (
                    "Alerts fire when total on hand drops to this number."
                  )}
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="item-reorder-quantity">Reorder quantity</Label>
                <Input
                  id="item-reorder-quantity"
                  type="number"
                  min="0"
                  step="0.0001"
                  inputMode="decimal"
                  placeholder="How much to buy"
                  value={values.reorder_quantity}
                  onChange={(event) => set("reorder_quantity", event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="item-safety-stock">Safety stock</Label>
                <Input
                  id="item-safety-stock"
                  type="number"
                  min="0"
                  step="0.0001"
                  inputMode="decimal"
                  placeholder="0"
                  value={values.safety_stock}
                  onChange={(event) => set("safety_stock", event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="item-lead-time">Lead time (days)</Label>
                <Input
                  id="item-lead-time"
                  type="number"
                  min="0"
                  max="365"
                  step="1"
                  inputMode="numeric"
                  placeholder="How long delivery takes"
                  value={values.lead_time_days}
                  onChange={(event) => set("lead_time_days", event.target.value)}
                />
              </div>
            </div>
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="item-supplier">Supplier</Label>
              <Input
                id="item-supplier"
                placeholder="Who to call"
                value={values.supplier_name}
                onChange={(event) => set("supplier_name", event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="item-supplier-sku">Supplier part number</Label>
              <Input
                id="item-supplier-sku"
                placeholder="Optional"
                value={values.supplier_sku}
                onChange={(event) => set("supplier_sku", event.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="item-notes">Notes</Label>
            <Textarea
              id="item-notes"
              rows={2}
              placeholder="Storage, mixing ratio, anything the crew needs"
              value={values.notes}
              onChange={(event) => set("notes", event.target.value)}
            />
          </div>

          {isEdit && (
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div>
                <Label htmlFor="item-active" className="font-medium">
                  Active
                </Label>
                <p className="text-xs text-muted-foreground">
                  Inactive items stay in reports but stop raising alerts.
                </p>
              </div>
              <Switch
                id="item-active"
                checked={values.is_active}
                onCheckedChange={(checked) => set("is_active", checked)}
              />
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={save.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!values.name.trim() || save.isPending}>
              {save.isPending && (
                <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
              )}
              {isEdit ? "Save changes" : "Track item"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
