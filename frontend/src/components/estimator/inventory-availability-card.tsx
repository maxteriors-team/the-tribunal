"use client";

import { AlertTriangle, CheckCircle2, PackageSearch } from "lucide-react";
import Link from "next/link";

import type {
  QuoteInventoryAvailability,
  QuoteInventoryAvailabilityItem,
} from "@/types/sales-wizard";

interface InventoryAvailabilityCardProps {
  availability: QuoteInventoryAvailability | null | undefined;
}

const STATUS_LABELS: Record<QuoteInventoryAvailabilityItem["status"], string> = {
  in_stock: "In stock",
  shortage: "Short",
  not_counted: "Not counted",
  untracked: "Not tracked",
};

export function InventoryAvailabilityCard({ availability }: InventoryAvailabilityCardProps) {
  if (!availability) return null;

  const incomplete = availability.not_counted_items + availability.untracked_items > 0;
  const needsAttention = availability.has_shortages || incomplete || !availability.has_requirements;
  const summary = availability.has_shortages
    ? `${availability.shortage_items} required item${availability.shortage_items === 1 ? " is" : "s are"} short.`
    : incomplete
      ? "Some required items need an opening count or inventory link."
      : availability.has_requirements
        ? "Current stock covers this package."
        : "This package has no inventory component SKUs configured.";
  const SummaryIcon = needsAttention ? AlertTriangle : CheckCircle2;

  return (
    <section
      className="space-y-3 rounded-xl border border-black/10 bg-white/70 p-4"
      aria-labelledby="quote-inventory-heading"
      data-testid="quote-inventory-availability"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <SummaryIcon
            className={`mt-0.5 size-4 shrink-0 ${
              needsAttention ? "text-amber-700" : "text-emerald-700"
            }`}
            aria-hidden="true"
          />
          <div>
            <h4 id="quote-inventory-heading" className="text-sm font-semibold text-[#1b1a18]">
              Inventory check
            </h4>
            <p className="text-xs text-[#6e675e]">{summary}</p>
          </div>
        </div>
        <Link
          href="/inventory"
          className="shrink-0 text-xs font-semibold text-[#6d5f4b] underline-offset-4 hover:underline"
        >
          Open inventory
        </Link>
      </div>

      {availability.items?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-xs">
            <caption className="sr-only">
              Required quote materials compared with current inventory
            </caption>
            <thead className="border-b border-black/10 text-[#6e675e]">
              <tr>
                <th className="py-2 pr-3 font-medium">Item</th>
                <th className="px-3 py-2 text-right font-medium">Required</th>
                <th className="px-3 py-2 text-right font-medium">On hand</th>
                <th className="py-2 pl-3 text-right font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.06]">
              {availability.items.map((item) => (
                <tr key={item.sku}>
                  <td className="py-2 pr-3">
                    <span className="font-medium text-[#1b1a18]">
                      {item.inventory_item_name || item.description || item.sku}
                    </span>
                    <span className="ml-2 text-[#8a8177]">{item.sku}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {quantity(item.required_quantity)} {item.unit_of_measure || ""}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {item.quantity_on_hand == null ? "—" : quantity(item.quantity_on_hand)}
                  </td>
                  <td className="py-2 pl-3 text-right font-medium">
                    {STATUS_LABELS[item.status]}
                    {item.status === "shortage" && item.shortfall != null
                      ? ` (${quantity(item.shortfall)} short)`
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-[#6e675e]">
          <PackageSearch className="size-4" aria-hidden="true" />
          Add component SKUs to the catalog package before relying on stock availability.
        </div>
      )}
      <p className="text-[11px] text-[#8a8177]">
        Quote creation does not reserve or consume stock. Inventory moves only when materials are
        issued to accepted work.
      </p>
    </section>
  );
}

function quantity(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
