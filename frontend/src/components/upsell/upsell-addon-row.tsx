"use client";

/**
 * One add-on on the on-site menu.
 *
 * Tapping anywhere on the row toggles it, which is the whole interaction for the
 * common case (sell one of something). The quantity stepper only appears once
 * the row is selected, so an unselected menu stays a flat list of prices rather
 * than a grid of controls.
 *
 * Selection is a neutral surface plus an accent border and a check mark, not an
 * accent wash: the row must stay readable in direct sunlight, and colour alone
 * never carries the state (`aria-pressed` does).
 */

import { Check, Minus, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { UpsellCatalogItem } from "@/lib/api/upsell";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/utils/number";

interface UpsellAddonRowProps {
  item: UpsellCatalogItem;
  quantity: number;
  onToggle: () => void;
  onQuantityChange: (next: number) => void;
  disabled?: boolean;
}

const MAX_QUANTITY = 99;

export function UpsellAddonRow({
  item,
  quantity,
  onToggle,
  onQuantityChange,
  disabled = false,
}: UpsellAddonRowProps) {
  const selected = quantity > 0;
  const lineTotal = item.unit_price * quantity;

  return (
    <li
      className={cn(
        "rounded-lg border transition-[border-color,background-color] duration-150 motion-reduce:transition-none",
        selected ? "border-primary bg-accent/40" : "border-border bg-card",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled}
        aria-pressed={selected}
        className="flex w-full items-start gap-3 rounded-lg p-4 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
      >
        <span
          aria-hidden="true"
          className={cn(
            "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border transition-[border-color,background-color] duration-150 motion-reduce:transition-none",
            selected
              ? "border-primary bg-primary text-primary-foreground"
              : "border-input",
          )}
        >
          {selected ? <Check className="size-3.5" /> : null}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-medium leading-snug">{item.name}</span>
          {item.description ? (
            <span className="mt-0.5 block text-sm text-muted-foreground">
              {item.description}
            </span>
          ) : null}
        </span>
        <span className="shrink-0 text-right">
          <span className="block font-semibold tabular-nums">
            {formatCurrency(item.unit_price)}
          </span>
          {/* A rate must never render like a job total: without the unit, an
              $18.50/ft item reads as an $18.50 job. */}
          {item.price_unit ? (
            <span className="block text-xs text-muted-foreground">
              {item.price_unit}
            </span>
          ) : null}
          {selected && quantity > 1 ? (
            <span className="block text-xs text-muted-foreground tabular-nums">
              {quantity} × = {formatCurrency(lineTotal)}
            </span>
          ) : null}
        </span>
      </button>

      {selected ? (
        <div
          className="flex items-center justify-between gap-3 border-t px-4 py-2"
          role="group"
          aria-label={`Quantity for ${item.name}`}
        >
          <span className="text-sm text-muted-foreground">Quantity</span>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-11"
              onClick={() => onQuantityChange(quantity - 1)}
              disabled={disabled || quantity <= 1}
              aria-label={`Remove one ${item.name}`}
            >
              <Minus className="size-4" aria-hidden="true" />
            </Button>
            <output
              className="w-8 text-center font-medium tabular-nums"
              aria-label={`${quantity} ${item.name}`}
            >
              {quantity}
            </output>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-11"
              onClick={() => onQuantityChange(quantity + 1)}
              disabled={disabled || quantity >= MAX_QUANTITY}
              aria-label={`Add one ${item.name}`}
            >
              <Plus className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  );
}
