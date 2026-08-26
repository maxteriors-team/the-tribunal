"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, PackageCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import { jobsApi } from "@/lib/api/jobs";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { JobInventoryPlan } from "@/types/inventory";

const AUTO_LOCATION = "__auto__";
const LOCATION_PARAMS = { include_inactive: false } as const;
const EMPTY_ALLOCATIONS: NonNullable<JobInventoryPlan["allocations"]> = [];

interface JobInventoryCompletionDialogProps {
  workspaceId: string;
  jobId: string;
  plan: JobInventoryPlan;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCompleted: () => void;
}

export function JobInventoryCompletionDialog({
  workspaceId,
  jobId,
  plan,
  open,
  onOpenChange,
  onCompleted,
}: JobInventoryCompletionDialogProps) {
  const queryClient = useQueryClient();
  const allocations = plan.allocations ?? EMPTY_ALLOCATIONS;
  const [actuals, setActuals] = useState<Record<string, string>>(() =>
    Object.fromEntries(allocations.map((line) => [line.id, String(line.planned_quantity)])),
  );
  const [locations, setLocations] = useState<Record<string, string>>({});

  const locationQuery = useQuery({
    queryKey: queryKeys.inventory.locations(workspaceId, LOCATION_PARAMS),
    queryFn: () => inventoryApi.listLocations(workspaceId, LOCATION_PARAMS),
    enabled: open,
  });

  const parsed = useMemo(
    () =>
      allocations.map((line) => {
        const actual = Number(actuals[line.id]);
        const availableForJob = Math.max(
          0,
          line.available_to_promise + (line.status === "reserved" ? line.planned_quantity : 0),
        );
        return {
          line,
          actual,
          shortage:
            Number.isFinite(actual) && actual >= 0 ? Math.max(0, actual - availableForJob) : 0,
        };
      }),
    [actuals, allocations],
  );
  const valid = parsed.every(
    ({ actual, shortage }) => Number.isFinite(actual) && actual >= 0 && shortage === 0,
  );

  const complete = useMutation({
    mutationFn: () =>
      jobsApi.completeWithInventory(workspaceId, jobId, {
        allocations: parsed.map(({ line, actual }) => ({
          allocation_id: line.id,
          actual_quantity: actual,
          source_location_id: locations[line.id] || null,
        })),
      }),
    onSuccess: () => {
      toast.success("Inventory posted and job completed");
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all(workspaceId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.jobs.materials(workspaceId, jobId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.inventory.all(workspaceId) });
      onOpenChange(false);
      onCompleted();
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Inventory changed. Review the quantities and retry.")),
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !complete.isPending && onOpenChange(next)}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Confirm Bistro inventory</DialogTitle>
          <DialogDescription>
            Enter what the crew actually used. This posts permanent COGS, deploys reusable gear,
            releases unused reservations, and completes the job together.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {parsed.map(({ line, actual, shortage }) => (
            <div key={line.id} className="space-y-3 rounded-lg border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{line.item_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {line.sku} · planned {line.planned_quantity} {line.unit_of_measure}
                  </p>
                </div>
                <Badge variant={line.behavior === "consumable" ? "secondary" : "outline"}>
                  {line.behavior === "consumable"
                    ? "Consume and post COGS"
                    : "Deploy — reusable"}
                </Badge>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor={`actual-${line.id}`}>Actual quantity</Label>
                  <Input
                    id={`actual-${line.id}`}
                    type="number"
                    min={0}
                    max={1_000_000_000}
                    step="0.0001"
                    inputMode="decimal"
                    value={actuals[line.id] ?? ""}
                    onChange={(event) =>
                      setActuals((current) => ({
                        ...current,
                        [line.id]: event.target.value,
                      }))
                    }
                    disabled={complete.isPending}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`location-${line.id}`}>Source location</Label>
                  <Select
                    value={locations[line.id] || AUTO_LOCATION}
                    onValueChange={(value) =>
                      setLocations((current) => ({
                        ...current,
                        [line.id]: value === AUTO_LOCATION ? "" : value,
                      }))
                    }
                    disabled={complete.isPending || locationQuery.isPending}
                  >
                    <SelectTrigger id={`location-${line.id}`}>
                      <SelectValue placeholder="Default stock location" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={AUTO_LOCATION}>Default stock location</SelectItem>
                      {(locationQuery.data ?? [])
                        .filter((location) => location.is_active)
                        .map((location) => (
                          <SelectItem key={location.id} value={location.id}>
                            {location.name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <p className="text-xs text-muted-foreground">
                Owned {line.quantity_on_hand} · reserved {line.quantity_reserved} · deployed{" "}
                {line.quantity_deployed} · available to promise {line.available_to_promise}
              </p>
              {shortage > 0 ? (
                <p className="text-sm font-medium text-destructive" role="alert">
                  Short by {shortage} {line.unit_of_measure} for this actual quantity.
                </p>
              ) : null}
              {!Number.isFinite(actual) || actual < 0 ? (
                <p className="text-sm font-medium text-destructive" role="alert">
                  Enter a quantity of zero or more.
                </p>
              ) : null}
            </div>
          ))}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={complete.isPending}>
            Cancel
          </Button>
          <Button onClick={() => complete.mutate()} disabled={!valid || complete.isPending}>
            {complete.isPending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <PackageCheck className="size-4" aria-hidden="true" />
            )}
            Post inventory and complete job
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
