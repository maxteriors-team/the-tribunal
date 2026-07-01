"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Printer, XCircle } from "lucide-react";
import { use, useState } from "react";

import { Button } from "@/components/ui/button";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Textarea } from "@/components/ui/textarea";
import { publicProposalsApi } from "@/lib/api/public-proposals";
import { queryKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils/date";
import { formatCurrency } from "@/lib/utils/number";
import type { PublicProposal } from "@/types/proposal";

interface PublicProposalPageProps {
  params: Promise<{ token: string }>;
}

// Print rules: strip the app chrome + action bar so a client can "Save as PDF"
// and get a clean, single-document proposal.
const PRINT_CSS = `
@media print {
  .no-print { display: none !important; }
  body { background: #fff !important; }
  .proposal-sheet { box-shadow: none !important; border: none !important; margin: 0 !important; max-width: none !important; }
}
`;

// The proposal is a client-facing document: render it on an explicit light
// surface (independent of the operator's app theme) so it looks professional
// for every recipient and prints cleanly to PDF.
const SHEET_TEXT = "text-slate-900";
const MUTED = "text-slate-500";

export default function PublicProposalPage({
  params,
}: PublicProposalPageProps) {
  const { token } = use(params);
  const queryClient = useQueryClient();
  const [showDecline, setShowDecline] = useState(false);
  const [declineReason, setDeclineReason] = useState("");

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.publicProposals.byToken(token),
    queryFn: () => publicProposalsApi.get(token),
    enabled: !!token,
    retry: false,
  });

  const approveMutation = useMutation({
    mutationFn: () => publicProposalsApi.approve(token),
    onSuccess: (result) => {
      queryClient.setQueryData<PublicProposal | undefined>(
        queryKeys.publicProposals.byToken(token),
        (prev) =>
          prev
            ? { ...prev, status: result.status, is_decided: true }
            : prev,
      );
    },
  });

  const declineMutation = useMutation({
    mutationFn: () => publicProposalsApi.decline(token, declineReason || undefined),
    onSuccess: (result) => {
      queryClient.setQueryData<PublicProposal | undefined>(
        queryKeys.publicProposals.byToken(token),
        (prev) =>
          prev
            ? { ...prev, status: result.status, is_decided: true }
            : prev,
      );
      setShowDecline(false);
    },
  });

  if (isPending) {
    return (
      <div className="min-h-screen bg-slate-100">
        <PageLoadingState className="min-h-screen" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-slate-100">
        <PageErrorState
          className="min-h-screen"
          message="This proposal link is invalid or has expired."
        />
      </div>
    );
  }

  const { branding } = data;
  const brand = branding.brand_color || "#0F172A";
  const accent = branding.accent_color || "#2563EB";
  const busy = approveMutation.isPending || declineMutation.isPending;
  const justApproved = approveMutation.isSuccess || data.status === "approved";
  const justDeclined = declineMutation.isSuccess || data.status === "declined";

  return (
    <div className={`min-h-screen bg-slate-100 py-6 px-4 sm:py-10 ${SHEET_TEXT}`}>
      <style>{PRINT_CSS}</style>

      <div className="mx-auto max-w-3xl space-y-4">
        {/* Action bar (screen only) */}
        <div className="no-print flex items-center justify-between">
          <span className={`text-sm ${MUTED}`}>Proposal {data.number}</span>
          <Button
            variant="outline"
            size="sm"
            className="border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900"
            onClick={() => window.print()}
          >
            <Printer className="mr-2 size-4" />
            Save as PDF
          </Button>
        </div>

        {/* The proposal sheet */}
        <div
          className="proposal-sheet overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
          style={{ borderTopColor: brand, borderTopWidth: 6 }}
        >
          {/* Header */}
          <div className="flex flex-col gap-4 border-b border-slate-200 p-6 sm:flex-row sm:items-start sm:justify-between sm:p-8">
            <div className="flex items-center gap-4">
              {branding.logo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={branding.logo_url}
                  alt={branding.business_name}
                  className="h-14 w-14 rounded object-contain"
                />
              ) : null}
              <div>
                <h1
                  className="text-xl font-bold leading-tight"
                  style={{ color: brand }}
                >
                  {branding.business_name}
                </h1>
                {branding.business_address ? (
                  <p className={`text-sm ${MUTED}`}>
                    {branding.business_address}
                  </p>
                ) : null}
                <p className={`text-sm ${MUTED}`}>
                  {[branding.business_phone, branding.business_email]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
            </div>
            <div className="sm:text-right">
              <p
                className="text-xs font-semibold uppercase tracking-wide"
                style={{ color: accent }}
              >
                Proposal
              </p>
              <p className="text-lg font-semibold">{data.number}</p>
              {data.issue_date ? (
                <p className={`text-sm ${MUTED}`}>{formatDate(data.issue_date)}</p>
              ) : null}
              {data.expiry_date ? (
                <p className={`text-sm ${MUTED}`}>
                  Valid until {formatDate(data.expiry_date)}
                </p>
              ) : null}
            </div>
          </div>

          {/* Status banners */}
          {justApproved ? (
            <div className="flex items-center gap-2 bg-emerald-50 px-6 py-3 text-emerald-700 sm:px-8">
              <CheckCircle2 className="size-5" />
              <span className="font-medium">
                You approved this proposal. Thank you!
              </span>
            </div>
          ) : justDeclined ? (
            <div className="flex items-center gap-2 bg-rose-50 px-6 py-3 text-rose-700 sm:px-8">
              <XCircle className="size-5" />
              <span className="font-medium">
                You declined this proposal. Thanks for letting us know.
              </span>
            </div>
          ) : data.is_expired ? (
            <div className="bg-amber-50 px-6 py-3 text-amber-700 sm:px-8">
              <span className="font-medium">
                This proposal has expired. Please contact us for an updated quote.
              </span>
            </div>
          ) : null}

          <div className="space-y-6 p-6 sm:p-8">
            {/* Prepared for + title */}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                {data.client_name ? (
                  <>
                    <p className={`text-xs font-semibold uppercase tracking-wide ${MUTED}`}>
                      Prepared for
                    </p>
                    <p className="text-lg font-medium">{data.client_name}</p>
                  </>
                ) : null}
              </div>
              {data.title ? (
                <p className="text-lg font-semibold" style={{ color: brand }}>
                  {data.title}
                </p>
              ) : null}
            </div>

            {data.intro ? (
              <p className="whitespace-pre-line text-sm leading-relaxed text-slate-600">
                {data.intro}
              </p>
            ) : null}

            {/* Line items */}
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr
                    className="text-left text-xs uppercase tracking-wide text-white"
                    style={{ backgroundColor: brand }}
                  >
                    <th className="rounded-l-md px-3 py-2 font-semibold">
                      Item
                    </th>
                    <th className="px-3 py-2 text-right font-semibold">Qty</th>
                    <th className="px-3 py-2 text-right font-semibold">
                      Unit price
                    </th>
                    <th className="px-3 py-2 text-right font-semibold">
                      Discount
                    </th>
                    <th className="rounded-r-md px-3 py-2 text-right font-semibold">
                      Amount
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.line_items.map((item, idx) => (
                    <tr key={idx} className="border-b border-slate-200 align-top">
                      <td className="px-3 py-3">
                        <p className="font-medium">{item.name}</p>
                        {item.description ? (
                          <p className={`text-xs ${MUTED}`}>{item.description}</p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {item.quantity}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {formatCurrency(item.unit_price, data.currency)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {item.discount
                          ? `−${formatCurrency(item.discount, data.currency)}`
                          : "—"}
                      </td>
                      <td className="px-3 py-3 text-right font-medium tabular-nums">
                        {formatCurrency(item.total, data.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Totals */}
            <div className="flex justify-end">
              <dl className="w-full max-w-xs space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt className={MUTED}>Subtotal</dt>
                  <dd className="tabular-nums">
                    {formatCurrency(data.subtotal, data.currency)}
                  </dd>
                </div>
                {data.discount_amount ? (
                  <div className="flex justify-between">
                    <dt className={MUTED}>Discount</dt>
                    <dd className="tabular-nums">
                      −{formatCurrency(data.discount_amount, data.currency)}
                    </dd>
                  </div>
                ) : null}
                {data.tax_amount ? (
                  <div className="flex justify-between">
                    <dt className={MUTED}>Tax</dt>
                    <dd className="tabular-nums">
                      {formatCurrency(data.tax_amount, data.currency)}
                    </dd>
                  </div>
                ) : null}
                <div
                  className="mt-1 flex justify-between border-t border-slate-200 pt-2 text-base font-bold"
                  style={{ color: brand }}
                >
                  <dt>Total</dt>
                  <dd className="tabular-nums">
                    {formatCurrency(data.total, data.currency)}
                  </dd>
                </div>
              </dl>
            </div>

            {/* Notes + terms */}
            {data.notes ? (
              <div>
                <p className={`text-xs font-semibold uppercase tracking-wide ${MUTED}`}>
                  Notes
                </p>
                <p className="whitespace-pre-line text-sm text-slate-600">
                  {data.notes}
                </p>
              </div>
            ) : null}
            {data.terms ? (
              <div>
                <p className={`text-xs font-semibold uppercase tracking-wide ${MUTED}`}>
                  Terms
                </p>
                <p className="whitespace-pre-line text-sm text-slate-600">
                  {data.terms}
                </p>
              </div>
            ) : null}

            {/* Approve / decline */}
            {!data.is_decided && !justApproved && !justDeclined ? (
              <div className="no-print space-y-3 border-t border-slate-200 pt-6">
                {showDecline ? (
                  <div className="space-y-3">
                    <Textarea
                      rows={3}
                      className="border-slate-300 bg-white text-slate-900 placeholder:text-slate-400"
                      value={declineReason}
                      onChange={(e) => setDeclineReason(e.target.value)}
                      placeholder="Optional: let us know why (helps us improve)…"
                    />
                    <div className="flex gap-2">
                      <Button
                        variant="destructive"
                        onClick={() => declineMutation.mutate()}
                        disabled={busy}
                      >
                        {declineMutation.isPending ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          "Confirm decline"
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => setShowDecline(false)}
                        disabled={busy}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <Button
                      size="lg"
                      className="flex-1 text-white"
                      style={{ backgroundColor: accent }}
                      onClick={() => approveMutation.mutate()}
                      disabled={busy}
                    >
                      {approveMutation.isPending ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <>
                          <CheckCircle2 className="mr-2 size-5" />
                          Approve proposal
                        </>
                      )}
                    </Button>
                    <Button
                      size="lg"
                      variant="outline"
                      className="flex-1 border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900"
                      onClick={() => setShowDecline(true)}
                      disabled={busy}
                    >
                      Decline
                    </Button>
                  </div>
                )}
                {(approveMutation.isError || declineMutation.isError) && (
                  <p className="text-sm text-destructive">
                    Something went wrong. Please refresh and try again.
                  </p>
                )}
              </div>
            ) : null}
          </div>

          {/* Footer */}
          {branding.footer ? (
            <div className={`border-t border-slate-200 bg-slate-50 px-6 py-4 text-center text-xs ${MUTED} sm:px-8`}>
              {branding.footer}
            </div>
          ) : null}
        </div>

        <p className={`no-print pb-4 text-center text-xs ${MUTED}`}>
          Powered by {branding.business_name}
        </p>
      </div>
    </div>
  );
}
