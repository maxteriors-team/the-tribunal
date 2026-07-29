"use client";

/**
 * Deposit panel for the public proposal page (shared by the plain-quote and
 * wizard-proposal views — both render inside `.proposal-view`).
 *
 * When the operator set a deposit percentage, the client sees the amount due
 * and a "Pay deposit" button that opens a Stripe Checkout Session and redirects
 * to Stripe's hosted page. Once paid it shows a confirmation instead. Renders
 * nothing when no deposit was requested.
 *
 * On a proposal where the client is still choosing a package, the caller passes
 * `amountDue` + `onPayInstead` so the panel quotes *their* pick and routes the
 * payment through acceptance — a direct checkout there would charge for the
 * package the rep proposed, not the one they chose.
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { publicProposalsApi } from "@/lib/api/public-proposals";
import { formatCurrency } from "@/lib/utils/number";
import type { PublicProposal } from "@/types/proposal";

interface DepositPanelProps {
  data: PublicProposal;
  /** Overrides the quote's deposit while a package is still being chosen. */
  amountDue?: number | null;
  /** Replaces direct checkout (used to accept-then-pay the chosen package). */
  onPayInstead?: () => void;
  payLabel?: string;
  busy?: boolean;
}

export function DepositPanel({
  data,
  amountDue,
  onPayInstead,
  payLabel,
  busy = false,
}: DepositPanelProps) {
  const [error, setError] = useState<string | null>(null);

  const checkout = useMutation({
    mutationFn: () => publicProposalsApi.depositCheckout(data.token),
    onSuccess: (result) => {
      // Hand off to Stripe's hosted payment page.
      window.location.href = result.url;
    },
    onError: () => {
      setError("Couldn’t start the payment. Please try again.");
    },
  });

  // `amountDue` is only supplied while the client is choosing; undefined means
  // "use the quote's own deposit", null/0 means this package owes nothing.
  const due = amountDue === undefined ? (data.deposit_amount ?? 0) : (amountDue ?? 0);

  // No deposit requested → render nothing.
  if (!due || due <= 0) return null;

  const amountLabel = formatCurrency(due, data.currency);
  const pctLabel =
    data.deposit_percentage != null
      ? `${Number(data.deposit_percentage)}% of your package total`
      : null;

  if (data.deposit_paid) {
    return (
      <div className="dep-panel paid">
        <div className="dep-info">
          <div className="dep-label">Deposit Paid</div>
          <div className="dep-amount">{amountLabel}</div>
        </div>
        <div className="dep-paid-badge">&#10003;&nbsp; Received — thank you!</div>
      </div>
    );
  }

  // An unpaid deposit on an expired/declined proposal can no longer be paid
  // (the checkout endpoint rejects it). Don't dangle a dead "Pay" button.
  if (data.is_expired || data.status === "declined") return null;

  return (
    <div className="dep-panel">
      <div className="dep-info">
        <div className="dep-label">Deposit Due Today</div>
        <div className="dep-amount">{amountLabel}</div>
        {pctLabel ? <div className="dep-sub">{pctLabel}</div> : null}
      </div>
      <button
        type="button"
        className="dep-pay-btn"
        disabled={checkout.isPending || busy}
        onClick={() => {
          setError(null);
          if (onPayInstead) {
            onPayInstead();
            return;
          }
          checkout.mutate();
        }}
      >
        {checkout.isPending || busy
          ? "Redirecting…"
          : (payLabel ?? "Pay Deposit")}
      </button>
      {error ? <div className="dep-error">{error}</div> : null}
    </div>
  );
}
