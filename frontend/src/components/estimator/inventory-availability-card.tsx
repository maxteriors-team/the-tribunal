"use client";

import { AlertTriangle, CheckCircle2, PackageSearch } from "lucide-react";
import Link from "next/link";

import type { QuoteInventoryAvailability } from "@/types/inventory";

interface InventoryAvailabilityCardProps {
  availability: QuoteInventoryAvailability | undefined;
  pending?: boolean;
  error?: string | null;
}

export function InventoryAvailabilityCard({
  availability,
  pending = false,
  error = null,
}: InventoryAvailabilityCardProps) {
  if (pending) {
    return (
      <section className="rounded-xl border border-black/10 bg-white/70 p-4 text-sm text-[#6e675e]">
        Checking inventory availability…
      </section>
    );
  }
  if (error) {
    return (
      <section className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        {error}
      </section>
    );
  }
  if (!availability) return null;

  const items = availability.items ?? [];
  const needsAttention = !availability.is_available;
  const shortageItems = items.filter((item) => item.shortage_quantity > 0).length;
  const summary = !availability.connected
    ? "Some required SKUs are not connected to active inventory."
    : shortageItems > 0
      ? `${shortageItems} required item${shortageItems === 1 ? " is" : "s are"} short.`
      : "Available-to-promise stock covers this package.";
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

      {items.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <caption className="sr-only">
              Required quote materials compared with available-to-promise inventory
            </caption>
            <thead className="border-b border-black/10 text-[#6e675e]">
              <tr>
                <th className="py-2 pr-3 font-medium">Item</th>
                <th className="px-3 py-2 text-right font-medium">Required</th>
                <th className="px-3 py-2 text-right font-medium">Owned</th>
                <th className="px-3 py-2 text-right font-medium">Reserved</th>
                <th className="px-3 py-2 text-right font-medium">Deployed</th>
                <th className="px-3 py-2 text-right font-medium">ATP</th>
                <th className="py-2 pl-3 text-right font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.06]">
              {items.map((item) => (
                <tr key={item.sku + item.inventory_behavior}>
                  <td className="py-2 pr-3">
                    <span className="font-medium text-[#1b1a18]">
                      {item.item_name || item.description || item.sku}
                    </span>
                    <span className="ml-2 text-[#8a8177]">{item.sku}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {quantity(item.required_quantity)} {item.unit_of_measure || ""}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {quantity(item.quantity_on_hand)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {quantity(item.quantity_reserved)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {quantity(item.quantity_deployed)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {quantity(item.available_to_promise)}
                  </td>
                  <td className="py-2 pl-3 text-right font-medium">
                    {!item.tracked
                      ? "Not tracked"
                      : !item.is_counted
                        ? "Not counted"
                        : item.is_available
                          ? "Available"
                          : `${quantity(item.shortage_quantity)} short`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-[#6e675e]">
          <PackageSearch className="size-4" aria-hidden="true" />
          Map inventory SKUs in Bistro pricing settings before relying on availability.
        </div>
      )}
      <p className="text-[11px] text-[#8a8177]">
        Quote creation does not move stock. Accepted work reserves it until job completion.
      </p>
    </section>
  );
}

function quantity(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
