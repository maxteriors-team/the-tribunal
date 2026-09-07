"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { publicProposalsApi } from "@/lib/api/public-proposals";
import { queryKeys } from "@/lib/query-keys";
import { formatCurrency } from "@/lib/utils/number";
import type { PublicProposal } from "@/types/proposal";

import "./proposal-theme.css";

interface ProposalPaymentPanelProps {
  data: PublicProposal;
}

function CheckoutButton({ token }: { token: PublicProposal["token"] }) {
  const queryClient = useQueryClient();
  const checkout = useMutation({
    mutationFn: () => publicProposalsApi.paymentCheckout(token),
    onSuccess: ({ url }) => {
      window.location.href = url;
    },
    onError: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.publicProposals.byToken(token) }),
  });
  return (
    <>
      <button
        type="button"
        className="dep-pay-btn"
        onClick={() => checkout.mutate()}
        disabled={checkout.isPending}
      >
        {checkout.isPending ? "Opening secure checkout…" : "Continue to secure checkout"}
      </button>
      {checkout.isError ? (
        <p className="dep-error" role="alert">
          Checkout could not open. Please try again.
        </p>
      ) : null}
    </>
  );
}

/** Retry and receipt state for the dedicated Permanent proposal payment path. */
export function ProposalPaymentPanel({ data }: ProposalPaymentPanelProps) {
  const choice = data.proposal_payment_choice;
  const amount = data.proposal_payment_amount;
  if (!choice || amount == null || data.status !== "approved") return null;

  const isDownPayment = choice === "fifty_percent_down";
  const schedule = isDownPayment ? "50% down" : "Payment in full";
  const completionBalance =
    data.payment_options?.completion_balance ?? Math.max(data.total - amount, 0);

  if (data.proposal_payment_paid) {
    return (
      <section className="dep-panel paid" aria-labelledby="proposal-payment-heading">
        <div className="dep-info">
          <h2 className="dep-label" id="proposal-payment-heading">
            Payment received
          </h2>
          <div className="dep-amount">{formatCurrency(amount, data.currency)}</div>
          <div className="dep-sub">
            {isDownPayment
              ? `${formatCurrency(completionBalance, data.currency)} remains due at completion.`
              : "Your proposal has been paid in full."}
          </div>
        </div>
        <div className="dep-paid-badge">✓ {schedule} received</div>
      </section>
    );
  }

  return (
    <section className="dep-panel" aria-labelledby="proposal-payment-heading">
      <div className="dep-info">
        <h2 className="dep-label" id="proposal-payment-heading">
          Payment due · {schedule}
        </h2>
        <div className="dep-amount">{formatCurrency(amount, data.currency)}</div>
        <div className="dep-sub">
          {isDownPayment
            ? `${formatCurrency(completionBalance, data.currency)} remains due at completion.`
            : "This completes your proposal balance."}
        </div>
      </div>
      {data.proposal_payment_required ? (
        <CheckoutButton token={data.token} />
      ) : (
        <div className="dep-paid-badge">Payment confirmation pending</div>
      )}
    </section>
  );
}
