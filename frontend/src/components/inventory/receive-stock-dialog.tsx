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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { inventoryApi } from "@/lib/api/inventory";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { InventoryItem } from "@/types/inventory";

interface ReceiveStockDialogProps {
  workspaceId: string;
  item: InventoryItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Receive stock at a known unit cost. This is the only movement that sets a
 * cost, so the field is required rather than optional: an unpriced receipt
 * would drag the item's weighted average toward zero and quietly understate
 * every job that consumes it afterwards.
 */
export function ReceiveStockDialog({
  workspaceId,
  item,
  open,
  onOpenChange,
}: ReceiveStockDialogProps) {
  const queryClient = useQueryClient();
  const [quantity, setQuantity] = useState("");
  const [unitCost, setUnitCost] = useState("");
  const [locationId, setLocationId] = useState<string>("");

  const locations = useQuery({
    queryKey: queryKeys.inventory.locations(workspaceId),
    queryFn: () => inventoryApi.listLocations(workspaceId),
    enabled: open && Boolean(workspaceId),
  });

  useEffect(() => {
    if (!open) return;
    setQuantity("");
    setUnitCost("");
    setLocationId("");
  }, [open, item?.id]);

  const receive = useMutation({
    mutationFn: () => {
      if (!item) throw new Error("No item selected");
      return inventoryApi.receive(workspaceId, item.id, {
        quantity: Number(quantity),
        unit_cost: Number(unitCost),
        location_id: locationId || undefined,
      });
    },
    onSuccess: (entry) => {
      toast.success(
        `Received ${entry.quantity_delta} ${item?.unit_of_measure ?? ""} of ${
          item?.name ?? "stock"
        }`.trim(),
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.inventory.all(workspaceId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.inventory.stock(workspaceId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.inventory.reorderReport(workspaceId),
      });
      onOpenChange(false);
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Failed to receive stock")),
  });

  const quantityValue = Number(quantity);
  const costValue = Number(unitCost);
  const valid =
    quantity !== "" &&
    unitCost !== "" &&
    Number.isFinite(quantityValue) &&
    Number.isFinite(costValue) &&
    quantityValue > 0 &&
    costValue >= 0;
  const total = valid ? quantityValue * costValue : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && receive.isPending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Receive {item?.name ?? "stock"}</DialogTitle>
          <DialogDescription>
            The cost you enter sets this item&apos;s average cost, which is what
            every job using it will be charged.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="receive-quantity">
                Quantity ({item?.unit_of_measure ?? "each"})
              </Label>
              <Input
                id="receive-quantity"
                type="number"
                min="0"
                step="0.0001"
                inputMode="decimal"
                placeholder="0"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="receive-cost">Cost per unit</Label>
              <Input
                id="receive-cost"
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                placeholder="0.00"
                value={unitCost}
                onChange={(event) => setUnitCost(event.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="receive-location">Location</Label>
            <Select
              value={locationId}
              onValueChange={setLocationId}
              disabled={locations.isLoading}
            >
              <SelectTrigger id="receive-location">
                <SelectValue placeholder="Default location" />
              </SelectTrigger>
              <SelectContent>
                {(locations.data ?? []).map((location) => (
                  <SelectItem key={location.id} value={location.id}>
                    {location.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {total !== null && (
            <p className="text-sm text-muted-foreground">
              Adds {formatCurrency(total)} of value to stock on hand.
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={receive.isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={() => receive.mutate()}
            disabled={!valid || receive.isPending}
          >
            {receive.isPending && (
              <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
            )}
            Receive stock
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
