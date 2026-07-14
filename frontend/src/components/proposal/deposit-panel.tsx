"use client";

/**
 * Deposit panel for the public proposal page (shared by the plain-quote and
 * wizard-proposal views — both render inside `.proposal-view`).
 *
 * When the operator set a deposit percentage, the client sees the amount due
 * and a "Pay deposit" button that opens a Stripe Checkout Session and redirects
 * to Stripe's hosted page. Once paid it shows a confirmation instead. Renders
 * nothing when no deposit was requested.
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { publicProposalsApi } from "@/lib/api/public-proposals";
import { formatCurrency } from "@/lib/utils/number";
import type { PublicProposal } from "@/types/proposal";

export function DepositPanel({ data }: { data: PublicProposal }) {
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

  // No deposit requested → render nothing.
  if (!data.deposit_amount || data.deposit_amount <= 0) return null;

  const amountLabel = formatCurrency(data.deposit_amount, data.currency);
  const pctLabel =
    data.deposit_percentage != null
      ? `${Number(data.deposit_percentage)}% of ${formatCurrency(data.total, data.currency)}`
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
        disabled={checkout.isPending}
        onClick={() => {
          setError(null);
          checkout.mutate();
        }}
      >
        {checkout.isPending ? "Redirecting…" : "Pay Deposit"}
      </button>
      {error ? <div className="dep-error">{error}</div> : null}
    </div>
  );
}
