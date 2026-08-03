"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Package, Undo2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCapabilities } from "@/hooks/useCapabilities";
import { inventoryApi } from "@/lib/api/inventory";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";

interface JobMaterialsPanelProps {
  workspaceId: string;
  jobId: string;
  readOnly?: boolean;
}

/**
 * Stock consumed delivering a job, pulled straight from inventory.
 *
 * Recording a material here is **not** the same as logging an expense: the
 * quantity leaves real stock at the item's current average cost, and the job's
 * `material_cost` comes only from this ledger. Removing a line returns the
 * stock instead of deleting the record, so the crew's mistake and its
 * correction both stay auditable.
 */
export function JobMaterialsPanel({
  workspaceId,
  jobId,
  readOnly = false,
}: JobMaterialsPanelProps) {
  const queryClient = useQueryClient();
  const { can } = useCapabilities();
  const canSeeCosts = can("billing:read");
  const canRecord = !readOnly && can("jobs:write");

  const [itemId, setItemId] = useState("");
  const [quantity, setQuantity] = useState("");

  const materials = useQuery({
    queryKey: queryKeys.jobs.materials(workspaceId, jobId),
    queryFn: () => inventoryApi.listJobMaterials(workspaceId, jobId),
    enabled: Boolean(workspaceId && jobId),
  });

  const itemsParams = { page_size: 200 };
  const items = useQuery({
    queryKey: queryKeys.inventory.list(workspaceId, itemsParams),
    queryFn: () => inventoryApi.listItems(workspaceId, itemsParams),
    enabled: canRecord && Boolean(workspaceId),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.jobs.materials(workspaceId, jobId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.jobs.profitability(workspaceId, jobId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.inventory.all(workspaceId),
    });
  };

  const addMaterial = useMutation({
    mutationFn: () =>
      inventoryApi.addJobMaterial(workspaceId, jobId, {
        item_id: itemId,
        quantity: Number(quantity),
      }),
    onSuccess: () => {
      toast.success("Material recorded");
      setItemId("");
      setQuantity("");
      invalidate();
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Failed to record material")),
  });

  const removeMaterial = useMutation({
    mutationFn: (entryId: string) =>
      inventoryApi.removeJobMaterial(workspaceId, jobId, entryId),
    onSuccess: () => {
      toast.success("Returned to stock");
      invalidate();
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Failed to return material")),
  });

  const entries = materials.data?.items ?? [];
  const usage = entries.filter((entry) => entry.reason === "job_usage");
  const returnedItemIds = new Set(
    entries
      .filter((entry) => entry.reason === "return_to_stock")
      .map((entry) => entry.item_id),
  );

  const quantityValue = Number(quantity);
  const canSubmit =
    itemId !== "" && Number.isFinite(quantityValue) && quantityValue > 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Materials used</h3>
        {canSeeCosts && entries.length > 0 && (
          <span className="text-sm tabular-nums">
            {formatCurrency(materials.data?.total_material_cost ?? 0)}
          </span>
        )}
      </div>

      {materials.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading materials…</p>
      ) : usage.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nothing pulled from stock for this job yet.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {usage.map((entry) => {
            const returned = returnedItemIds.has(entry.item_id);
            return (
              <li
                key={entry.id}
                className="flex items-center justify-between gap-3 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Package className="size-4 shrink-0" aria-hidden="true" />
                    <span className="truncate">
                      {entry.item_name ?? "Item"}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {Math.abs(entry.quantity_delta)} from{" "}
                    {entry.location_name ?? "stock"}
                    {returned ? " · returned" : ""}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {canSeeCosts && (
                    <span className="text-sm tabular-nums">
                      {formatCurrency(Math.abs(entry.value_delta))}
                    </span>
                  )}
                  {canRecord && !returned && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Return ${entry.item_name ?? "material"} to stock`}
                      disabled={removeMaterial.isPending}
                      onClick={() => removeMaterial.mutate(entry.id)}
                    >
                      <Undo2 className="size-4" aria-hidden="true" />
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {canRecord && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[12rem] flex-1 space-y-1">
            <Label htmlFor="material-item" className="text-xs">
              Item
            </Label>
            <Select value={itemId} onValueChange={setItemId}>
              <SelectTrigger id="material-item">
                <SelectValue placeholder="Pick from stock" />
              </SelectTrigger>
              <SelectContent>
                {(items.data?.items ?? []).map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.name} · {item.quantity_on_hand} {item.unit_of_measure}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="w-28 space-y-1">
            <Label htmlFor="material-quantity" className="text-xs">
              Quantity
            </Label>
            <Input
              id="material-quantity"
              type="number"
              min="0"
              step="0.0001"
              inputMode="decimal"
              placeholder="0"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
            />
          </div>
          <Button
            onClick={() => addMaterial.mutate()}
            disabled={!canSubmit || addMaterial.isPending}
          >
            {addMaterial.isPending && (
              <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
            )}
            Use on job
          </Button>
        </div>
      )}
    </div>
  );
}
