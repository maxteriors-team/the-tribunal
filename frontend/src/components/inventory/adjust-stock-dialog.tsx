"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
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
  RadioGroup,
  RadioGroupItem,
} from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { inventoryApi } from "@/lib/api/inventory";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { InventoryItem } from "@/types/inventory";

type AdjustMode = "count" | "write_off";

interface AdjustStockDialogProps {
  workspaceId: string;
  item: InventoryItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Two different corrections, deliberately not merged into one number field:
 *
 * - a **physical count** reconciles to what is actually on the shelf;
 * - a **write-off** removes stock as waste, which is reported apart from cost
 *   of goods sold so spoilage never hides inside gross margin.
 *
 * Either way the ledger keeps the original rows: a correction is a new entry.
 */
export function AdjustStockDialog({
  workspaceId,
  item,
  open,
  onOpenChange,
}: AdjustStockDialogProps) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<AdjustMode>("count");
  const [amount, setAmount] = useState("");
  const [locationId, setLocationId] = useState("");
  const [note, setNote] = useState("");

  const locations = useQuery({
    queryKey: queryKeys.inventory.locations(workspaceId),
    queryFn: () => inventoryApi.listLocations(workspaceId),
    enabled: open && Boolean(workspaceId),
  });

  const adjust = useMutation({
    mutationFn: () => {
      if (!item) throw new Error("No item selected");
      const value = Number(amount);
      return inventoryApi.adjust(workspaceId, item.id, {
        quantity_on_hand: mode === "count" ? value : undefined,
        write_off_quantity: mode === "write_off" ? value : undefined,
        location_id: locationId || undefined,
        note: note.trim() || undefined,
      });
    },
    onSuccess: () => {
      toast.success(
        mode === "count" ? "Count recorded" : "Stock written off",
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
      toast.error(getApiErrorMessage(error, "Failed to adjust stock")),
  });

  const value = Number(amount);
  const valid =
    amount !== "" &&
    Number.isFinite(value) &&
    (mode === "count" ? value >= 0 : value > 0);

  const unit = item?.unit_of_measure ?? "each";

  // Cleared on close, so the dialog always opens on a fresh count.
  const handleOpenChange = (next: boolean) => {
    if (!next && adjust.isPending) return;
    if (!next) {
      setMode("count");
      setAmount("");
      setLocationId("");
      setNote("");
    }
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Adjust {item?.name ?? "stock"}</DialogTitle>
          <DialogDescription>
            Currently {item?.quantity_on_hand ?? 0} {unit} on hand across all
            locations.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <RadioGroup
            value={mode}
            onValueChange={(next) => setMode(next as AdjustMode)}
            className="gap-2"
          >
            <div className="flex items-start gap-2 rounded-md border p-3">
              <RadioGroupItem value="count" id="adjust-mode-count" className="mt-0.5" />
              <Label htmlFor="adjust-mode-count" className="font-normal">
                <span className="block font-medium">Physical count</span>
                <span className="block text-xs text-muted-foreground">
                  Set on hand to what you counted. The difference is logged.
                </span>
              </Label>
            </div>
            <div className="flex items-start gap-2 rounded-md border p-3">
              <RadioGroupItem
                value="write_off"
                id="adjust-mode-write-off"
                className="mt-0.5"
              />
              <Label htmlFor="adjust-mode-write-off" className="font-normal">
                <span className="block font-medium">Write off</span>
                <span className="block text-xs text-muted-foreground">
                  Spilled, expired, or damaged. Reported apart from job costs.
                </span>
              </Label>
            </div>
          </RadioGroup>

          <div className="space-y-1.5">
            <Label htmlFor="adjust-amount">
              {mode === "count" ? `Counted quantity (${unit})` : `Quantity to remove (${unit})`}
            </Label>
            <Input
              id="adjust-amount"
              type="number"
              min="0"
              step="0.0001"
              inputMode="decimal"
              placeholder="0"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="adjust-location">Location</Label>
            <Select
              value={locationId}
              onValueChange={setLocationId}
              disabled={locations.isLoading}
            >
              <SelectTrigger id="adjust-location">
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

          <div className="space-y-1.5">
            <Label htmlFor="adjust-note">Reason (optional)</Label>
            <Textarea
              id="adjust-note"
              rows={2}
              placeholder="e.g. quarterly count, drum cracked in transit"
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={adjust.isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={() => adjust.mutate()}
            disabled={!valid || adjust.isPending}
          >
            {adjust.isPending && (
              <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
            )}
            {mode === "count" ? "Record count" : "Write off"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
