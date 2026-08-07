"use client";

/**
 * The pinned running total and primary action.
 *
 * Fixed in the thumb zone so the number stays readable while the add-on menu
 * scrolls behind it: a technician quoting a price out loud at the customer's
 * door must never have to scroll to read it. Its inner content shares the same
 * rail width as the page header and list, so all three edges align.
 *
 * Deliberately carries exactly ONE action. A second button here would compete
 * with the total for width on a 360px phone and force the most important number
 * on the screen to truncate; secondary actions belong in the content above.
 */

import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/utils/number";

interface UpsellSummaryBarProps {
  itemCount: number;
  total: number;
  /**
   * Yearly subscription total, kept on its own line rather than added to
   * `total`. A recurring plan summed into a one-time figure produces a number
   * the customer never agreed to pay.
   */
  recurringTotal?: number;
  actionLabel: string;
  onAction: () => void;
  disabled?: boolean;
  pending?: boolean;
  pendingLabel?: string;
  /**
   * Why the action is unavailable, shown above the bar. Carries the reason next
   * to the disabled control rather than leaving a dead button with no
   * explanation — the technician is standing in front of the customer.
   */
  notice?: string | null;
}

export function UpsellSummaryBar({
  itemCount,
  total,
  recurringTotal = 0,
  actionLabel,
  onAction,
  disabled = false,
  pending = false,
  pendingLabel = "Working…",
  notice = null,
}: UpsellSummaryBarProps) {
  return (
    <div
      // `pb-[env(safe-area-inset-bottom)]` keeps the action clear of the home
      // indicator on notched phones, which is where this screen is used.
      className="sticky bottom-0 z-10 border-t bg-background/95 backdrop-blur-sm pb-[env(safe-area-inset-bottom)]"
    >
      {notice ? (
        <p
          role="status"
          className="mx-auto w-full max-w-screen-sm border-b border-dashed px-4 py-2 text-xs text-muted-foreground"
        >
          {notice}
        </p>
      ) : null}
      <div className="mx-auto flex w-full max-w-screen-sm items-center gap-4 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted-foreground">
            {itemCount === 0 && recurringTotal === 0
              ? "Nothing selected"
              : itemCount === 0
                ? "Care plan"
                : `${itemCount} add-on${itemCount === 1 ? "" : "s"}`}
          </p>
          {/* Polite live region wraps BOTH figures: a screen-reader user adding
              a care plan must hear the yearly line appear, not just the total. */}
          <div aria-live="polite">
            {total > 0 || recurringTotal === 0 ? (
              <p className="text-xl font-semibold tabular-nums">{formatCurrency(total)}</p>
            ) : null}
            {recurringTotal > 0 ? (
              <p
                className={cn(
                  "tabular-nums",
                  total > 0 ? "text-xs text-muted-foreground" : "text-xl font-semibold",
                )}
              >
                {total > 0 ? "+ " : ""}
                {formatCurrency(recurringTotal)}/yr
              </p>
            ) : null}
          </div>
        </div>
        <Button
          size="lg"
          onClick={onAction}
          disabled={disabled || pending}
          className="min-h-11 shrink-0"
        >
          {pending ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              {pendingLabel}
            </>
          ) : (
            actionLabel
          )}
        </Button>
      </div>
    </div>
  );
}
