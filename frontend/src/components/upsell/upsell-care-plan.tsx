"use client";

/**
 * Care Plan section — the recurring half of the on-site sale.
 *
 * Two things make this different from the add-on list above it:
 *
 * 1. **The price is a function of an input the technician gathers.** Plans price
 *    as `base + per_fixture × (count − free)`, so the fixture count is a real
 *    pricing field, not a note. It sits above the tiers because the prices move
 *    when it changes, and a number that moves under your thumb after you have
 *    read it aloud is worse than one you set first.
 * 2. **It is billed yearly, not once.** Every price here is suffixed `/yr` and
 *    the running total keeps it on its own line — a subscription folded into a
 *    one-time total is a number the customer never agreed to.
 *
 * Hidden entirely when the workspace configures no tiers: not every trade sells
 * maintenance, and a dead section is worse than no section.
 */

import { Check } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { UpsellCarePlanOption } from "@/lib/api/upsell";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/utils/number";

interface UpsellCarePlanSectionProps {
  options: UpsellCarePlanOption[];
  freeFixtures: number;
  fixtureCount: number;
  selectedKey: string | null;
  onFixtureCountChange: (next: number) => void;
  onSelect: (key: string | null) => void;
  disabled?: boolean;
}

const MAX_FIXTURES = 1000;

export function UpsellCarePlanSection({
  options,
  freeFixtures,
  fixtureCount,
  selectedKey,
  onFixtureCountChange,
  onSelect,
  disabled = false,
}: UpsellCarePlanSectionProps) {
  if (options.length === 0) return null;

  return (
    <section aria-labelledby="upsell-care-plan-heading" className="mt-6">
      <h2 id="upsell-care-plan-heading" className="font-medium">
        Care plan
      </h2>
      <p className="mt-0.5 text-sm text-muted-foreground">
        Keep their system maintained. Billed yearly.
      </p>

      <div className="mt-3 flex items-center justify-between gap-4 rounded-lg border bg-card p-4">
        <Label htmlFor="upsell-fixture-count" className="text-sm font-normal">
          Fixtures on site
          <span className="block text-xs text-muted-foreground">
            First {freeFixtures} included
          </span>
        </Label>
        <Input
          id="upsell-fixture-count"
          type="number"
          inputMode="numeric"
          min={0}
          max={MAX_FIXTURES}
          value={fixtureCount}
          disabled={disabled}
          onChange={(event) => {
            const parsed = Number.parseInt(event.target.value, 10);
            onFixtureCountChange(
              Number.isNaN(parsed) ? 0 : Math.max(0, Math.min(MAX_FIXTURES, parsed)),
            );
          }}
          className="h-11 w-24 text-center text-base tabular-nums"
        />
      </div>

      <ul className="mt-2 flex flex-col gap-2">
        {options.map((option) => {
          const selected = option.key === selectedKey;
          return (
            <li key={option.key}>
              <button
                type="button"
                // Re-tapping the selected tier clears it: a technician who opened
                // the plan to read a price out loud needs a way back to "no plan"
                // that is not starting the proposal over.
                onClick={() => onSelect(selected ? null : option.key)}
                disabled={disabled}
                aria-pressed={selected}
                className={cn(
                  "flex w-full items-start gap-3 rounded-lg border p-4 text-left outline-none transition-[border-color,background-color] duration-150 focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50 motion-reduce:transition-none",
                  selected
                    ? "border-primary bg-accent/40"
                    : "border-border bg-card hover:border-primary/50",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border transition-[border-color,background-color] duration-150 motion-reduce:transition-none",
                    selected
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-input",
                  )}
                >
                  {selected ? <Check className="size-3.5" /> : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium leading-snug">{option.name}</span>
                  <span className="mt-0.5 block text-sm text-muted-foreground">
                    {option.visits} visit{option.visits === 1 ? "" : "s"} a year
                    {option.repair_discount > 0
                      ? ` · ${Math.round(option.repair_discount * 100)}% off repairs`
                      : ""}
                  </span>
                  {option.blurb ? (
                    <span className="mt-1 block text-sm text-muted-foreground">
                      {option.blurb}
                    </span>
                  ) : null}
                </span>
                <span className="shrink-0 text-right">
                  <span className="block font-semibold tabular-nums">
                    {formatCurrency(option.price)}
                  </span>
                  {/* Never omit: the same number without "/yr" is a one-time price. */}
                  <span className="block text-xs text-muted-foreground">/yr</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
