"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useCapabilities } from "@/hooks/useCapabilities";
import { inventoryApi } from "@/lib/api/inventory";
import { queryKeys } from "@/lib/query-keys";
import { formatDateTime } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import {
  LEDGER_REASON_LABELS,
  type InventoryItem,
  type InventoryLedgerReason,
} from "@/types/inventory";

const OUTBOUND_REASONS: readonly InventoryLedgerReason[] = [
  "job_usage",
  "sale",
  "shrinkage",
  "transfer_out",
];

interface ItemLedgerSheetProps {
  workspaceId: string;
  item: InventoryItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * The audit trail for one item: every movement, newest first, with the on-hand
 * quantity that each one left behind.
 *
 * Nothing here is editable. A mistake is corrected by posting a new movement,
 * which is why a wrong count and its fix both stay visible.
 */
export function ItemLedgerSheet({
  workspaceId,
  item,
  open,
  onOpenChange,
}: ItemLedgerSheetProps) {
  const { can } = useCapabilities();
  const canSeeCosts = can("billing:read");

  const query = useQuery({
    queryKey: queryKeys.inventory.ledger(workspaceId, item?.id ?? "", {
      page_size: 100,
    }),
    queryFn: () =>
      inventoryApi.listLedger(workspaceId, item!.id, { page_size: 100 }),
    enabled: open && Boolean(workspaceId) && Boolean(item),
  });

  const entries = query.data?.items ?? [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{item?.name ?? "Stock"} history</SheetTitle>
          <SheetDescription>
            Every movement, newest first. Entries are never edited; corrections
            are posted as new movements.
          </SheetDescription>
        </SheetHeader>

        <div className="px-4 pb-6">
          {query.isLoading ? (
            <PageLoadingState message="Loading history..." />
          ) : query.isError ? (
            <PageErrorState
              message={getApiErrorMessage(query.error, "Failed to load history")}
              onRetry={() => void query.refetch()}
            />
          ) : entries.length === 0 ? (
            <PageEmptyState
              title="No movements yet"
              description="Receiving stock or using it on a job will show up here."
            />
          ) : (
            <ol className="divide-y">
              {entries.map((entry) => {
                const outbound = OUTBOUND_REASONS.includes(entry.reason);
                // Compose the signed quantity as one token so the sign never
                // wraps or spaces away from its number.
                const signed = `${entry.quantity_delta > 0 ? "+" : ""}${
                  entry.quantity_delta
                } ${item?.unit_of_measure ?? ""}`.trim();
                return (
                  <li key={entry.id} className="flex gap-3 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={outbound ? "outline" : "secondary"}>
                          {LEDGER_REASON_LABELS[entry.reason]}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {entry.location_name ?? "—"} ·{" "}
                          {formatDateTime(entry.occurred_at)}
                        </span>
                      </div>
                      {entry.note && (
                        <p className="mt-1 truncate text-sm text-muted-foreground">
                          {entry.note}
                        </p>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      <div
                        className={`text-sm font-medium tabular-nums ${
                          outbound ? "text-destructive" : "text-emerald-600"
                        }`}
                      >
                        {signed}
                      </div>
                      <div className="text-xs text-muted-foreground tabular-nums">
                        {canSeeCosts
                          ? `${formatCurrency(entry.unit_cost)}/unit · `
                          : ""}
                        {entry.quantity_after} on hand
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
