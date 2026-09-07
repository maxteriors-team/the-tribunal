"use client";

/**
 * Client-facing plain line-item quote (dark/gold premium presentation).
 *
 * Renders line-item quotes without structured package pricing in the same luxury
 * theme as `ClientProposalView`; a plain quote may still carry customer preview
 * media. Shares `proposal-theme.css` and the decline pattern; only the itemized
 * table and totals are bespoke.
 */
import Image from "next/image";
import { useState } from "react";

import { TermsAndConditionsLink } from "@/components/shared/terms-and-conditions-link";
import { formatDate } from "@/lib/utils/date";
import { formatCurrency } from "@/lib/utils/number";
import type { ProposalPaymentChoice, PublicProposal } from "@/types/proposal";

import { DepositPanel } from "./deposit-panel";
import { PermanentPaymentOptions } from "./financing-estimate";
import { renderTextWithLinks } from "./linkify-text";
import { proposalAccentVars } from "./proposal-brand";
import { proposalFontVars } from "./proposal-fonts";
import { ProposalPaymentPanel } from "./proposal-payment-panel";

import "./proposal-theme.css";

interface PlainQuoteViewProps {
  data: PublicProposal;
  justApproved: boolean;
  justDeclined: boolean;
  busy: boolean;
  actionError: boolean;
  onApprove: (paymentOption?: ProposalPaymentChoice | null) => void;
  onDecline: (reason: string) => void;
}

interface QuotePreview {
  image: string;
  caption: string;
}

function proposalPreviews(document: Record<string, unknown> | null | undefined): QuotePreview[] {
  const mockups = document?.mockups;
  if (!Array.isArray(mockups)) return [];
  return mockups.flatMap((mockup) => {
    if (!mockup || typeof mockup !== "object") return [];
    const record = mockup as Record<string, unknown>;
    const image = record.image;
    if (typeof image !== "string" || !/^data:image\/(?:jpeg|png|webp);base64,/.test(image)) {
      return [];
    }
    return [
      {
        image,
        caption:
          typeof record.caption === "string" && record.caption.trim()
            ? record.caption.trim()
            : "Proposed permanent lighting preview",
      },
    ];
  });
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
  const previews = proposalPreviews(data.proposal_document);
  const [showDecline, setShowDecline] = useState(false);
  const [declineReason, setDeclineReason] = useState("");
  const [paymentOption, setPaymentOption] = useState<ProposalPaymentChoice | null>(
    data.proposal_payment_choice ?? null,
  );

  const decided = data.is_decided || justApproved || justDeclined;
  const approved = justApproved || data.status === "approved";
  const currency = data.currency;
  const priceRange = data.price_range;
  const paymentFinancing =
    data.proposal_document?.service === "permanent" && data.financing ? data.financing : null;
  const paymentOptions = data.payment_options ?? null;
  const paymentOptionRequired =
    data.proposal_document?.service === "permanent" && paymentOptions !== null;
  const paymentOptionMissing = paymentOptionRequired && paymentOption === null;
  const selectedPaymentAmount =
    paymentOption === "fifty_percent_down"
      ? paymentOptions?.fifty_percent_down_amount
      : paymentOption === "pay_in_full"
        ? paymentOptions?.pay_in_full_amount
        : null;
  const submitApproval = () => {
    if (paymentOptionMissing) return;
    if (paymentOptionRequired) onApprove(paymentOption);
    else onApprove();
  };
  const approvalLabel = paymentOptionMissing
    ? "Choose payment method"
    : paymentOptionRequired
      ? "Approve and pay"
      : "Yes, approve this proposal";
  const approvalAriaLabel =
    selectedPaymentAmount && !paymentOptionMissing
      ? `Approve and pay ${formatCurrency(selectedPaymentAmount, currency)}`
      : approvalLabel;

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
    <div
      className={`proposal-view ${proposalFontVars}`}
      style={proposalAccentVars(branding.brand_color, branding.accent_color)}
    >
      <div className="present-nav no-print">
        <div className="present-nav-brand">{`${brandName} \u00b7 Proposal ${data.number}`}</div>
        <div className="present-nav-actions">
          <button type="button" className="send-email-nav-btn" onClick={() => window.print()}>
            Save as PDF
          </button>
        </div>
      </div>

      <div className="present-body">
        {justApproved ? (
          <div className="pp-banner ok" role="status">
            You approved this proposal. Thank you!
          </div>
        ) : justDeclined ? (
          <div className="pp-banner no" role="status">
            You declined this proposal. Thanks for letting us know.
          </div>
        ) : data.is_expired ? (
          <div className="pp-banner" role="status">
            This proposal has expired. Please contact us for an updated quote.
          </div>
        ) : null}

        {/* Hero */}
        <div className="present-hero">
          {/* This page is the receipt of record, so it carries the brand mark
              the same way the rich proposal view does. */}
          {branding.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- workspace-uploaded logo URL
            <img src={branding.logo_url} alt={brandName} className="pp-logo" />
          ) : null}
          <div className="present-eyebrow">Proposal {data.number}</div>
          {data.client_name ? (
            <div className="present-hi">
              Prepared for <strong>{data.client_name}</strong>
            </div>
          ) : null}
          <h1 className="pq-hero-title">{data.title || brandName}</h1>
          <div className="present-ornament">
            <div className="present-ornament-line" />
            <div className="present-ornament-diamond" />
            <div className="present-ornament-line r" />
          </div>
          {dateLine ? <div className="pp-meta">{dateLine}</div> : null}
        </div>

        {data.intro ? <p className="pq-intro">{data.intro}</p> : null}

        {previews.length > 0 ? (
          <section className="pmock-section" aria-labelledby="permanent-preview-heading">
            <h2 className="section-heading" id="permanent-preview-heading">
              Preview your permanent lighting
            </h2>
            <div className={`pmock-grid${previews.length === 1 ? " single" : ""}`}>
              {previews.map((preview) => (
                <figure className="pmock-item" key={preview.image}>
                  <Image
                    src={preview.image}
                    alt={preview.caption}
                    width={1280}
                    height={720}
                    sizes="(max-width: 620px) 100vw, 960px"
                    style={{ height: "auto" }}
                    unoptimized
                  />
                  <figcaption className="pmock-cap">{preview.caption}</figcaption>
                </figure>
              ))}
            </div>
          </section>
        ) : null}

        {!paymentOptionRequired && priceRange ? (
          <section className="pq-range" aria-labelledby="proposal-price-heading">
            <h2 className="section-heading" id="proposal-price-heading">
              Estimated project range
            </h2>
            <div className="pq-range-values">
              <div className="pq-range-endpoint">
                <span className="pq-range-label">Lower amount</span>
                <strong className="pq-range-amount">
                  {formatCurrency(priceRange.low, currency)}
                </strong>
              </div>
              <div className="pq-range-endpoint">
                <span className="pq-range-label">Higher amount</span>
                <strong className="pq-range-amount">
                  {formatCurrency(priceRange.high, currency)}
                </strong>
              </div>
            </div>
            <p className="pq-range-note">
              Approving locks in the lower amount of {formatCurrency(priceRange.low, currency)}. Any
              increase requires separate confirmation.
            </p>
          </section>
        ) : null}

        {/* Scope; permanent payment prices appear only in the three option cards below. */}
        <section className="pq-table-wrap" aria-labelledby="quote-summary-heading">
          <h2 className="section-heading" id="quote-summary-heading">
            {paymentOptionRequired ? "Project scope" : "Investment summary"}
          </h2>
          <table className="pq-table">
            <thead>
              <tr>
                <th>{paymentOptionRequired ? "Included work" : "Item"}</th>
                {!paymentOptionRequired ? (
                  <>
                    <th className="pq-col-detail">Qty</th>
                    <th className="pq-col-detail">Unit Price</th>
                    <th className="pq-col-detail">Discount</th>
                    <th>Amount</th>
                  </>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {data.line_items.map((item, idx) => (
                <tr key={`${item.name}-${idx}`}>
                  <td>
                    <div className="pq-item-name">{item.name}</div>
                    {item.description ? (
                      <div className="pq-item-desc">{item.description}</div>
                    ) : null}
                    {!paymentOptionRequired ? (
                      <div className="pq-item-meta">
                        {item.quantity} × {formatCurrency(item.unit_price, currency)}
                        {item.discount
                          ? ` · ${formatCurrency(item.discount, currency)} discount`
                          : ""}
                      </div>
                    ) : null}
                  </td>
                  {!paymentOptionRequired ? (
                    <>
                      <td className="pq-num pq-col-detail">{item.quantity}</td>
                      <td className="pq-num pq-col-detail">
                        {formatCurrency(item.unit_price, currency)}
                      </td>
                      <td className="pq-num pq-col-detail muted">
                        {item.discount ? `−${formatCurrency(item.discount, currency)}` : "None"}
                      </td>
                      <td className="pq-amount">{formatCurrency(item.total, currency)}</td>
                    </>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* Permanent proposals keep all visible prices in the payment-option cards. */}
        {!paymentOptionRequired ? (
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
                    {"−"}
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
        ) : null}

        {!decided && paymentOptionRequired ? (
          <>
            <PermanentPaymentOptions
              financing={paymentFinancing}
              paymentOptions={paymentOptions}
              currency={data.currency}
              value={paymentOption}
              onChange={setPaymentOption}
              disabled={busy}
            />
            {paymentOptionMissing ? (
              <p className="payment-selection-required" role="status">
                Select 50% down or pay in full before accepting this proposal.
              </p>
            ) : null}
          </>
        ) : null}

        <ProposalPaymentPanel data={data} />

        {/* Permanent payments never reuse the legacy deposit checkout. */}
        {!paymentOptionRequired ? <DepositPanel data={data} busy={busy} /> : null}

        {/* Notes + terms */}
        {data.notes ? (
          <section className="pp-terms">
            <h2 className="section-heading">Notes</h2>
            <p>{data.notes}</p>
          </section>
        ) : null}
        {data.terms ? (
          <section className="pp-terms">
            <h2 className="section-heading">Terms</h2>
            <p>{data.terms}</p>
          </section>
        ) : null}

        {/* Approve / decline */}
        <div className="cta-section no-print">
          {decided ? (
            <>
              <div className="cta-eyebrow">{approved ? "Approved" : "Response Recorded"}</div>
              <div className="cta-heading">
                {approved ? "Thank you." : "Thanks for letting us know."}
              </div>
              <div className="cta-sub">
                {contactLine
                  ? `Questions? Contact us: ${contactLine}`
                  : "Questions? We\u2019re right here."}
              </div>
            </>
          ) : showDecline ? (
            <>
              <div className="cta-eyebrow">Before You Go</div>
              <h2 className="cta-heading">Mind telling us why?</h2>
              <div className="pp-decline">
                <label htmlFor="proposal-decline-reason">Optional reason</label>
                <textarea
                  id="proposal-decline-reason"
                  rows={3}
                  value={declineReason}
                  onChange={(e) => setDeclineReason(e.target.value)}
                  placeholder="Let us know why. This helps us improve."
                />
                <div className="pp-decline-row">
                  <button
                    type="button"
                    className="cta-btn-danger"
                    disabled={busy}
                    onClick={() => onDecline(declineReason)}
                  >
                    {busy ? "Sending…" : "Confirm decline"}
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
              <h2 className="cta-heading">Let&rsquo;s make it happen.</h2>
              <div className="cta-sub">
                {contactLine
                  ? `Questions? Contact us: ${contactLine}`
                  : "Questions? We\u2019re right here."}
              </div>
              <div className="cta-buttons">
                <button
                  type="button"
                  className="cta-btn-primary"
                  disabled={busy || paymentOptionMissing}
                  aria-label={busy ? "Approving" : approvalAriaLabel}
                  onClick={submitApproval}
                >
                  {busy ? "Approving…" : approvalLabel}
                </button>
                <button
                  type="button"
                  className="cta-btn-secondary"
                  disabled={busy}
                  onClick={() => setShowDecline(true)}
                >
                  No, decline
                </button>
              </div>
            </>
          )}
          {actionError ? (
            <div className="pp-error" role="alert">
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
          <div className="pp-footer-note">{renderTextWithLinks(branding.footer)}</div>
        ) : null}
        <div className="pp-footer-note">
          <TermsAndConditionsLink />
        </div>
      </div>
    </div>
  );
}
