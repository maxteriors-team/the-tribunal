"use client";

import { PackageX } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ReorderRow } from "@/types/inventory";

interface LowStockBannerProps {
  rows: ReorderRow[];
  /** True while the list is already filtered to low stock. */
  filtered: boolean;
  onToggleFilter: () => void;
}

/**
 * The decision, above the evidence: which items are at or below their reorder
 * point, ordered by days of cover so the one that runs out first reads first.
 *
 * Hidden entirely when nothing is low — a permanently visible "all good" strip
 * trains operators to stop reading this row.
 */
export function LowStockBanner({
  rows,
  filtered,
  onToggleFilter,
}: LowStockBannerProps) {
  if (rows.length === 0) return null;

  const [first, second] = rows;
  const single = rows.length === 1;
  const remaining = rows.length - (second ? 2 : 1);
  const names = [first, second]
    .filter((row): row is ReorderRow => Boolean(row))
    .map((row) => row.item_name)
    .join(", ");

  // Name the item once. With several low items the first one is named again
  // because it is the one the cover estimate is about; with one item that would
  // just repeat the sentence before it.
  const days = first.days_of_cover;
  const cover =
    days === null || days === undefined
      ? "Record usage on jobs to see how long the remaining stock lasts."
      : `${single ? "Runs" : `${first.item_name} runs`} out in about ${days} day${
          days === 1 ? "" : "s"
        } at recent usage.`;

  return (
    <div
      role="status"
      className="flex flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950 sm:flex-row sm:items-center sm:justify-between dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-100"
    >
      <div className="flex gap-3">
        <PackageX className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <div className="space-y-0.5">
          <p className="text-sm font-medium">
            {rows.length} item{rows.length === 1 ? "" : "s"} at or below the
            reorder point
          </p>
          <p className="text-sm">
            {names}
            {remaining > 0 ? ` and ${remaining} more` : ""}. {cover}
          </p>
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={onToggleFilter}
        className="shrink-0 border-amber-400 bg-transparent hover:bg-amber-100 dark:border-amber-600 dark:hover:bg-amber-900/50"
      >
        {filtered ? "Show all items" : "Show only these"}
      </Button>
    </div>
  );
}
