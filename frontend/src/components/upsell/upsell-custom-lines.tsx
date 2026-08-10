"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const MAX_CUSTOM_LINES = 10;

export interface UpsellCustomLineDraft {
  id: string;
  name: string;
  quantity: string;
  unitPrice: string;
}

export interface UpsellCustomLineRequest {
  name: string;
  quantity: number;
  unit_price: number;
}

let nextCustomLineId = 0;

export function newUpsellCustomLine(): UpsellCustomLineDraft {
  nextCustomLineId += 1;
  return {
    id: `custom-upsell-${nextCustomLineId}`,
    name: "",
    quantity: "1",
    unitPrice: "",
  };
}

export function toCustomLineRequest(
  line: UpsellCustomLineDraft,
): UpsellCustomLineRequest | null {
  const name = line.name.trim();
  const quantity = Number(line.quantity);
  const unitPrice = Number(line.unitPrice);
  if (
    !name ||
    !Number.isFinite(quantity) ||
    quantity <= 0 ||
    quantity > 1000 ||
    !Number.isFinite(unitPrice) ||
    unitPrice <= 0 ||
    unitPrice > 100_000
  ) {
    return null;
  }
  return { name, quantity, unit_price: unitPrice };
}

export function customLineSubtotal(lines: readonly UpsellCustomLineDraft[]): number {
  return lines.reduce((total, line) => {
    const request = toCustomLineRequest(line);
    return total + (request ? request.quantity * request.unit_price : 0);
  }, 0);
}

export function UpsellCustomLines({
  lines,
  onChange,
  disabled = false,
}: {
  lines: UpsellCustomLineDraft[];
  onChange: (lines: UpsellCustomLineDraft[]) => void;
  disabled?: boolean;
}) {
  const patch = (id: string, values: Partial<UpsellCustomLineDraft>) => {
    onChange(lines.map((line) => (line.id === id ? { ...line, ...values } : line)));
  };

  return (
    <section className="space-y-3" aria-labelledby="custom-line-items-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="custom-line-items-heading" className="font-medium">
            Custom line items
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Add one-off work that is not in the price book.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          className="min-h-11 shrink-0"
          onClick={() => onChange([...lines, newUpsellCustomLine()])}
          disabled={disabled || lines.length >= MAX_CUSTOM_LINES}
        >
          <Plus className="size-4" aria-hidden="true" />
          Add custom
        </Button>
      </div>

      {lines.length > 0 ? (
        <ul className="space-y-3">
          {lines.map((line, index) => {
            const valid = toCustomLineRequest(line) !== null;
            const hintId = `${line.id}-hint`;
            return (
              <li key={line.id} className="space-y-3 rounded-lg border bg-card p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">Custom item {index + 1}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-11"
                    onClick={() => onChange(lines.filter((item) => item.id !== line.id))}
                    disabled={disabled}
                    aria-label={`Remove ${line.name.trim() || `custom item ${index + 1}`}`}
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                  </Button>
                </div>

                <label
                  htmlFor={`${line.id}-name`}
                  className="block space-y-1.5 text-sm font-medium"
                >
                  Description
                  <Input
                    id={`${line.id}-name`}
                    value={line.name}
                    maxLength={200}
                    placeholder="Lift rental, extra labor…"
                    autoComplete="off"
                    disabled={disabled}
                    aria-describedby={hintId}
                    onChange={(event) => patch(line.id, { name: event.target.value })}
                  />
                </label>

                <div className="grid grid-cols-2 gap-3">
                  <label
                    htmlFor={`${line.id}-quantity`}
                    className="block space-y-1.5 text-sm font-medium"
                  >
                    Quantity
                    <Input
                      id={`${line.id}-quantity`}
                      type="number"
                      inputMode="decimal"
                      min="0.01"
                      max="1000"
                      step="1"
                      value={line.quantity}
                      disabled={disabled}
                      aria-describedby={hintId}
                      onChange={(event) => patch(line.id, { quantity: event.target.value })}
                    />
                  </label>
                  <label
                    htmlFor={`${line.id}-price`}
                    className="block space-y-1.5 text-sm font-medium"
                  >
                    Price each
                    <Input
                      id={`${line.id}-price`}
                      type="number"
                      inputMode="decimal"
                      min="0.01"
                      max="100000"
                      step="0.01"
                      placeholder="$0.00"
                      value={line.unitPrice}
                      disabled={disabled}
                      aria-describedby={hintId}
                      onChange={(event) => patch(line.id, { unitPrice: event.target.value })}
                    />
                  </label>
                </div>

                <p
                  id={hintId}
                  className={valid ? "sr-only" : "text-sm text-muted-foreground"}
                >
                  Enter a description, quantity, and customer price above zero.
                </p>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
