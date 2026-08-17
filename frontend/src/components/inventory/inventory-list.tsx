"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  History,
  MoreHorizontal,
  Package,
  PackagePlus,
  Pencil,
  Plus,
  Scale,
  Search,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { inventoryApi } from "@/lib/api/inventory";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S, REALTIME } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { InventoryItem } from "@/types/inventory";

import { AdjustStockDialog } from "./adjust-stock-dialog";
import { InventoryItemDialog } from "./inventory-item-dialog";
import { ItemLedgerSheet } from "./item-ledger-sheet";
import { LowStockBanner } from "./low-stock-banner";
import { ReceiveStockDialog } from "./receive-stock-dialog";

type ActiveDialog = "edit" | "receive" | "adjust" | "ledger" | null;

/**
 * The inventory home: what needs buying (banner), then what is on hand (table).
 *
 * Cost columns are omitted, not zeroed, for callers without `billing:read` —
 * the API redacts those fields to 0, and rendering "$0.00" would read as a fact
 * rather than a hidden value. Quantities stay visible for everyone, since
 * "three buckets left on the truck" is the field crew's whole question.
 */
export function InventoryList() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const { can } = useCapabilities();
  const canSeeCosts = can("billing:read");
  const canManageStock = can("billing:write");

  const [search, setSearch] = useState("");
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [selected, setSelected] = useState<InventoryItem | null>(null);
  const [dialog, setDialog] = useState<ActiveDialog>(null);

  const listParams = {
    search: search.trim() || undefined,
    low_stock: lowStockOnly || undefined,
    include_inactive: true,
    page_size: 200,
  };

  const items = useQuery({
    queryKey: queryKeys.inventory.list(workspaceId ?? "", listParams),
    queryFn: () => inventoryApi.listItems(workspaceId ?? "", listParams),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });

  const reorder = useQuery({
    queryKey: queryKeys.inventory.reorderReport(workspaceId ?? ""),
    queryFn: () => inventoryApi.reorderReport(workspaceId ?? ""),
    enabled: Boolean(workspaceId),
    ...REALTIME,
  });

  const remove = useMutation({
    mutationFn: (id: string) => inventoryApi.deleteItem(workspaceId ?? "", id),
    onSuccess: () => {
      toast.success("Item removed");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.inventory.all(workspaceId ?? ""),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.inventory.reorderReport(workspaceId ?? ""),
      });
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Failed to remove item")),
  });

  const openFor = (item: InventoryItem | null, next: ActiveDialog) => {
    setSelected(item);
    setDialog(next);
  };

  const newItemButton = canManageStock ? (
    <Button size="sm" onClick={() => openFor(null, "edit")}>
      <Plus className="mr-1.5 size-4" aria-hidden="true" />
      Track item
    </Button>
  ) : null;

  const rows = items.data?.items ?? [];

  let body: React.ReactNode;
  if (!workspaceId || items.isLoading) {
    body = <PageLoadingState message="Loading inventory..." />;
  } else if (items.isError) {
    body = (
      <PageErrorState
        message={getApiErrorMessage(items.error, "Failed to load inventory")}
        onRetry={() => void items.refetch()}
      />
    );
  } else if (rows.length === 0) {
    body = (
      <PageEmptyState
        icon={<Package className="size-8" aria-hidden="true" />}
        title={
          search || lowStockOnly ? "No items match" : "Nothing tracked yet"
        }
        description={
          search || lowStockOnly
            ? "Try a different search, or clear the low-stock filter."
            : "Track the chemicals, parts, and materials you buy so jobs can pull from real stock and reorder alerts can fire."
        }
        action={search || lowStockOnly ? undefined : newItemButton ?? undefined}
      />
    );
  } else {
    body = (
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">On hand</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Reorder at</TableHead>
              {canSeeCosts && (
                <TableHead className="hidden text-right lg:table-cell">Avg cost</TableHead>
              )}
              {canSeeCosts && (
                <TableHead className="hidden text-right md:table-cell">Value</TableHead>
              )}
              <TableHead className="hidden md:table-cell">Supplier</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((item) => (
              <TableRow key={item.id} className={item.is_active ? "" : "opacity-60"}>
                <TableCell className="font-medium">
                  <div className="flex flex-wrap items-center gap-2">
                    {item.name}
                    {item.is_low_stock && (
                      <Badge variant="destructive">Low stock</Badge>
                    )}
                    {!item.is_active && <Badge variant="outline">Archived</Badge>}
                  </div>
                  {item.sku && (
                    <div className="text-xs text-muted-foreground">{item.sku}</div>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {item.quantity_on_hand}
                  <span className="ml-1 text-xs text-muted-foreground">
                    {item.unit_of_measure}
                  </span>
                </TableCell>
                <TableCell className="hidden text-right tabular-nums text-muted-foreground sm:table-cell">
                  {item.reorder_point ?? "Not managed"}
                </TableCell>
                {canSeeCosts && (
                  <TableCell className="hidden text-right tabular-nums lg:table-cell">
                    {formatCurrency(item.avg_unit_cost)}
                  </TableCell>
                )}
                {canSeeCosts && (
                  <TableCell className="hidden text-right tabular-nums md:table-cell">
                    {formatCurrency(item.total_value)}
                  </TableCell>
                )}
                <TableCell className="hidden text-muted-foreground md:table-cell">
                  {item.supplier_name || "—"}
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Actions for ${item.name}`}
                      >
                        <MoreHorizontal className="size-4" aria-hidden="true" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => openFor(item, "ledger")}>
                        <History className="mr-2 size-4" aria-hidden="true" />
                        History
                      </DropdownMenuItem>
                      {canManageStock && (
                        <>
                          <DropdownMenuItem onClick={() => openFor(item, "receive")}>
                            <PackagePlus className="mr-2 size-4" aria-hidden="true" />
                            Receive stock
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => openFor(item, "adjust")}>
                            <Scale className="mr-2 size-4" aria-hidden="true" />
                            Count or write off
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => openFor(item, "edit")}>
                            <Pencil className="mr-2 size-4" aria-hidden="true" />
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            variant="destructive"
                            onClick={() => remove.mutate(item.id)}
                          >
                            <Trash2 className="mr-2 size-4" aria-hidden="true" />
                            Remove
                          </DropdownMenuItem>
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <LowStockBanner
        rows={reorder.data?.items ?? []}
        filtered={lowStockOnly}
        onToggleFilter={() => setLowStockOnly((previous) => !previous)}
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative w-full max-w-xs">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            className="pl-8"
            placeholder="Search items or suppliers"
            aria-label="Search inventory"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={lowStockOnly ? "secondary" : "outline"}
            size="sm"
            aria-pressed={lowStockOnly}
            onClick={() => setLowStockOnly((previous) => !previous)}
          >
            Low stock only
          </Button>
          {newItemButton}
        </div>
      </div>

      {body}

      {workspaceId && (
        <>
          <InventoryItemDialog
            // Keyed on the item so opening a different one mounts a fresh form
            // rather than syncing props into state.
            key={selected?.id ?? "new-item"}
            workspaceId={workspaceId}
            item={dialog === "edit" ? selected : null}
            open={dialog === "edit"}
            onOpenChange={(next) => setDialog(next ? "edit" : null)}
          />
          <ReceiveStockDialog
            workspaceId={workspaceId}
            item={selected}
            open={dialog === "receive"}
            onOpenChange={(next) => setDialog(next ? "receive" : null)}
          />
          <AdjustStockDialog
            workspaceId={workspaceId}
            item={selected}
            open={dialog === "adjust"}
            onOpenChange={(next) => setDialog(next ? "adjust" : null)}
          />
          <ItemLedgerSheet
            workspaceId={workspaceId}
            item={selected}
            open={dialog === "ledger"}
            onOpenChange={(next) => setDialog(next ? "ledger" : null)}
          />
        </>
      )}
    </div>
  );
}
