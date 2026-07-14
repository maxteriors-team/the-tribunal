"use client";

/**
 * Client-facing plain line-item quote (dark/gold premium presentation).
 *
 * Renders quotes that have no sales-wizard snapshot (`proposal_document` is
 * null) in the same luxury theme as `ClientProposalView`, so every recipient —
 * builder proposal or simple itemized quote — gets one consistent brand
 * experience. Shares `proposal-theme.css` tokens, fonts, and the Approve /
 * Decline CTA pattern; only the itemized table + totals are bespoke.
 */
import { useState } from "react";

import { formatDate } from "@/lib/utils/date";
import { formatCurrency } from "@/lib/utils/number";
import type { PublicProposal } from "@/types/proposal";

import { DepositPanel } from "./deposit-panel";
import { proposalFontVars } from "./proposal-fonts";

import "./proposal-theme.css";

interface PlainQuoteViewProps {
  data: PublicProposal;
  justApproved: boolean;
  justDeclined: boolean;
  busy: boolean;
  actionError: boolean;
  onApprove: () => void;
  onDecline: (reason: string) => void;
}

export function PlainQuoteView({
  data,
  justApproved,
  justDeclined,
  busy,
  actionError,
  onApprove,
  onDecline,
}: PlainQuoteViewProps) {
  const { branding } = data;
  const brandName = branding.business_name;
  const [showDecline, setShowDecline] = useState(false);
  const [declineReason, setDeclineReason] = useState("");

  const decided = data.is_decided || justApproved || justDeclined;
  const approved = justApproved || data.status === "approved";
  const currency = data.currency;

  const contactLine = [branding.business_phone, branding.business_email]
    .filter(Boolean)
    .join(" \u00b7 ");

  const dateLine = [
    data.issue_date ? `Issued ${formatDate(data.issue_date)}` : null,
    data.expiry_date ? `Valid until ${formatDate(data.expiry_date)}` : null,
  ]
    .filter(Boolean)
    .join(" \u00b7 ");

  return (
    <div className={`proposal-view ${proposalFontVars}`}>
      <div className="present-nav no-print">
        <div className="present-nav-brand">
          {`${brandName} \u00b7 Proposal ${data.number}`}
        </div>
        <div className="present-nav-actions">
          <button
            type="button"
            className="send-email-nav-btn"
            onClick={() => window.print()}
          >
            &#9113; Save as PDF
          </button>
        </div>
      </div>

      <div className="present-body">
        {justApproved ? (
          <div className="pp-banner ok">
            &#10003;&nbsp; You approved this proposal. Thank you!
          </div>
        ) : justDeclined ? (
          <div className="pp-banner no">
            You declined this proposal. Thanks for letting us know.
          </div>
        ) : data.is_expired ? (
          <div className="pp-banner">
            This proposal has expired. Please contact us for an updated quote.
          </div>
        ) : null}

        {/* Hero */}
        <div className="present-hero">
          <div className="present-eyebrow">Proposal {data.number}</div>
          {data.client_name ? (
            <div className="present-hi">
              Prepared for <strong>{data.client_name}</strong>
            </div>
          ) : null}
          <div className="pq-hero-title">{data.title || brandName}</div>
          <div className="present-ornament">
            <div className="present-ornament-line" />
            <div className="present-ornament-diamond" />
            <div className="present-ornament-line r" />
          </div>
          {dateLine ? <div className="pp-meta">{dateLine}</div> : null}
        </div>

        {data.intro ? <p className="pq-intro">{data.intro}</p> : null}

        {/* Line items */}
        <div className="pq-table-wrap" style={{ marginTop: 48 }}>
          <div className="section-heading">Investment Summary</div>
          <table className="pq-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Qty</th>
                <th>Unit Price</th>
                <th>Discount</th>
                <th>Amount</th>
              </tr>
            </thead>
            <tbody>
              {data.line_items.map((item, idx) => (
                <tr key={idx}>
                  <td>
                    <div className="pq-item-name">{item.name}</div>
                    {item.description ? (
                      <div className="pq-item-desc">{item.description}</div>
                    ) : null}
                  </td>
                  <td className="pq-num">{item.quantity}</td>
                  <td className="pq-num">
                    {formatCurrency(item.unit_price, currency)}
                  </td>
                  <td className="pq-num muted">
                    {item.discount
                      ? `\u2212${formatCurrency(item.discount, currency)}`
                      : "\u2014"}
                  </td>
                  <td className="pq-amount">
                    {formatCurrency(item.total, currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Totals */}
        <div className="pq-totals">
          <div className="pq-totals-inner">
            <div className="pq-total-row">
              <span>Subtotal</span>
              <strong>{formatCurrency(data.subtotal, currency)}</strong>
            </div>
            {data.discount_amount ? (
              <div className="pq-total-row">
                <span>Discount</span>
                <strong>
                  {"\u2212"}
                  {formatCurrency(data.discount_amount, currency)}
                </strong>
              </div>
            ) : null}
            {data.tax_amount ? (
              <div className="pq-total-row">
                <span>Tax</span>
                <strong>{formatCurrency(data.tax_amount, currency)}</strong>
              </div>
            ) : null}
            <div className="pq-total-row grand">
              <span>Total</span>
              <strong>{formatCurrency(data.total, currency)}</strong>
            </div>
          </div>
        </div>

        {/* Deposit (pay online) */}
        <DepositPanel data={data} />

        {/* Notes + terms */}
        {data.notes ? (
          <div className="pp-terms" style={{ marginTop: 48 }}>
            <div className="section-heading">Notes</div>
            <p>{data.notes}</p>
          </div>
        ) : null}
        {data.terms ? (
          <div className="pp-terms">
            <div className="section-heading">Terms</div>
            <p>{data.terms}</p>
          </div>
        ) : null}

        {/* Approve / decline */}
        <div className="cta-section no-print">
          {decided ? (
            <>
              <div className="cta-eyebrow">
                {approved ? "Approved" : "Response Recorded"}
              </div>
              <div className="cta-heading">
                {approved
                  ? "Thank you."
                  : "Thanks for letting us know."}
              </div>
              <div className="cta-sub">
                {contactLine
                  ? `Questions? Reach us anytime \u2014 ${contactLine}`
                  : "Questions? We\u2019re right here."}
              </div>
            </>
          ) : showDecline ? (
            <>
              <div className="cta-eyebrow">Before You Go</div>
              <div className="cta-heading">Mind telling us why?</div>
              <div className="pp-decline">
                <textarea
                  rows={3}
                  value={declineReason}
                  onChange={(e) => setDeclineReason(e.target.value)}
                  placeholder="Optional: let us know why (helps us improve)…"
                />
                <div className="pp-decline-row">
                  <button
                    type="button"
                    className="cta-btn-danger"
                    disabled={busy}
                    onClick={() => onDecline(declineReason)}
                  >
                    {busy ? "Sending…" : "Confirm Decline"}
                  </button>
                  <button
                    type="button"
                    className="cta-btn-secondary"
                    disabled={busy}
                    onClick={() => setShowDecline(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="cta-eyebrow">Ready to Move Forward</div>
              <div className="cta-heading">Let&rsquo;s make it happen.</div>
              <div className="cta-sub">
                {contactLine
                  ? `Questions? We\u2019re right here \u2014 ${contactLine}`
                  : "Questions? We\u2019re right here."}
              </div>
              <div className="cta-buttons">
                <button
                  type="button"
                  className="cta-btn-primary"
                  disabled={busy}
                  onClick={onApprove}
                >
                  {busy ? "Approving…" : <>&#10003;&nbsp; Approve Proposal</>}
                </button>
                <button
                  type="button"
                  className="cta-btn-secondary"
                  disabled={busy}
                  onClick={() => setShowDecline(true)}
                >
                  Decline
                </button>
              </div>
            </>
          )}
          {actionError ? (
            <div className="pp-error">
              Something went wrong. Please refresh and try again.
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="pp-meta">
          {branding.business_address ? <>{branding.business_address}</> : null}
          {contactLine ? (
            <>
              {branding.business_address ? <br /> : null}
              {contactLine}
            </>
          ) : null}
        </div>
        {branding.footer ? (
          <div className="pp-footer-note">{branding.footer}</div>
        ) : null}
      </div>
    </div>
  );
}
