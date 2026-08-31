"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { publicComparisonsApi } from "@/lib/api/public-comparisons";

interface ComparisonDeclineProps {
  token: string;
  /** True when this estimate was already declined, so the page stops asking. */
  declined: boolean;
}

/**
 * The client's way to say no on a shared estimate.
 *
 * Without it the link is a dead end: they can read a price but cannot answer
 * it, so the rep keeps chasing a decision that was already made. Deliberately
 * *only* decline — an estimate is a price to consider, and accepting is what
 * the proposal is for, so there is no approve button to mistake for one.
 */
export function ComparisonDecline({ token, declined }: ComparisonDeclineProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");

  const decline = useMutation({
    mutationFn: () => publicComparisonsApi.decline(token, reason),
  });

  // `declined` covers a reload of an already-declined estimate; the mutation's
  // own success covers the tab that just did it.
  if (declined || decline.isSuccess) {
    return (
      <div className="cmp-decline cmp-decline-done" role="status">
        Thanks for letting us know. We won&rsquo;t chase this one.
      </div>
    );
  }

  if (!open) {
    return (
      <div className="cmp-decline">
        <button type="button" className="cmp-decline-link" onClick={() => setOpen(true)}>
          Not moving forward?
        </button>
      </div>
    );
  }

  return (
    <div className="cmp-decline">
      <label className="cmp-decline-label" htmlFor="cmp-decline-reason">
        Mind telling us why? (optional)
      </label>
      <textarea
        id="cmp-decline-reason"
        className="cmp-decline-input"
        rows={3}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        maxLength={1000}
        placeholder="Price, timing, went another direction…"
      />
      <div className="cmp-decline-row">
        <button
          type="button"
          className="cmp-decline-confirm"
          disabled={decline.isPending}
          onClick={() => decline.mutate()}
        >
          {decline.isPending ? "Sending…" : "Confirm"}
        </button>
        <button
          type="button"
          className="cmp-decline-cancel"
          disabled={decline.isPending}
          onClick={() => setOpen(false)}
        >
          Cancel
        </button>
      </div>
      {decline.isError ? (
        <p className="cmp-decline-error" role="alert">
          That didn&rsquo;t send. Please try again.
        </p>
      ) : null}
    </div>
  );
}
