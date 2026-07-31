"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { use, useEffect, useRef } from "react";

import { PublicInvoiceView } from "@/components/invoice/public-invoice-view";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { publicInvoicesApi } from "@/lib/api/public-invoices";
import { queryKeys } from "@/lib/query-keys";

interface PublicInvoicePageProps {
  params: Promise<{ token: string }>;
}

export default function PublicInvoicePage({ params }: PublicInvoicePageProps) {
  const { token } = use(params);
  const queryClient = useQueryClient();

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.publicInvoices.byToken(token),
    queryFn: () => publicInvoicesApi.get(token),
    enabled: !!token,
    retry: false,
  });

  // Reliable payment capture: on return from Stripe (`?payment=paid`) the
  // webhook may not have landed yet. Reconcile against Stripe directly and poll
  // a few times with backoff until the invoice reads paid, so a delayed or
  // missing webhook never leaves a customer staring at a bill they just paid.
  // Mirrors the proposal deposit flow.
  const reconciledRef = useRef(false);
  useEffect(() => {
    if (reconciledRef.current) return;
    const search = new URLSearchParams(window.location.search);
    if (search.get("payment") !== "paid") return;
    reconciledRef.current = true;
    let cancelled = false;
    void (async () => {
      for (let attempt = 0; attempt < 5 && !cancelled; attempt += 1) {
        try {
          const status = await publicInvoicesApi.paymentStatus(token);
          if (status.is_paid) {
            await queryClient.invalidateQueries({
              queryKey: queryKeys.publicInvoices.byToken(token),
            });
            return;
          }
        } catch {
          // Ignore and retry; the page degrades to the unpaid state.
        }
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, queryClient]);

  if (isPending) {
    return (
      <div className="min-h-screen bg-[#0a0a0a]">
        <PageLoadingState className="min-h-screen" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-[#0a0a0a]">
        <PageErrorState
          className="min-h-screen"
          message="This invoice link is invalid or is no longer available."
        />
      </div>
    );
  }

  return <PublicInvoiceView data={data} />;
}
