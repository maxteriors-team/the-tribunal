"use client";

/**
 * Client-facing invoice (dark/gold premium presentation).
 *
 * Deliberately the sibling of `PlainQuoteView`: same theme tokens, fonts,
 * itemized table, and totals anatomy, so a customer who approved the proposal
 * recognises the invoice that follows it.
 *
 * Where the proposal leads with persuasion, the invoice leads with the number
 * owed — its single job is "pay the balance". The hero is the amount due, and
 * the totals block carries the deposit already credited so it is obvious *why*
 * the balance is less than the total rather than looking like a pricing error.
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { publicInvoicesApi } from "@/lib/api/public-invoices";
import { formatDate } from "@/lib/utils/date";
import { formatCurrency } from "@/lib/utils/number";
import type { PublicInvoice } from "@/types/public-invoice";

import { renderTextWithLinks } from "../proposal/linkify-text";
import { proposalFontVars } from "../proposal/proposal-fonts";

import "../proposal/proposal-theme.css";
import "./invoice-theme.css";

interface PublicInvoiceViewProps {
  data: PublicInvoice;
}

export function PublicInvoiceView({ data }: PublicInvoiceViewProps) {
  const { branding } = data;
  const brandName = branding.business_name;
  const currency = data.currency;
  const [error, setError] = useState<string | null>(null);

  const checkout = useMutation({
    mutationFn: () => publicInvoicesApi.pay(data.token),
    onSuccess: (result) => {
      // Hand off to Stripe's hosted payment page.
      window.location.href = result.url;
    },
    onError: () => {
      setError("We couldn't start the payment. Please try again.");
    },
  });

  const contactLine = [branding.business_phone, branding.business_email]
    .filter(Boolean)
    .join(" \u00b7 ");

  const dateLine = [
    data.issue_date ? `Issued ${formatDate(data.issue_date)}` : null,
    data.due_date ? `Due ${formatDate(data.due_date)}` : null,
  ]
    .filter(Boolean)
    .join(" \u00b7 ");

  // A partly-paid invoice needs the credit spelled out; a fresh one doesn't.
  const hasCredit = data.amount_paid > 0;

  return (
    <div className={`proposal-view invoice-view ${proposalFontVars}`}>
      <div className="present-nav no-print">
        <div className="present-nav-brand">
          {`${brandName} \u00b7 Invoice ${data.number}`}
        </div>
        <div className="present-nav-actions">
          <button
            type="button"
            className="send-email-nav-btn"
            onClick={() => window.print()}
          >
            Save as PDF
          </button>
        </div>
      </div>

      <main className="present-body">
        {/* Status. role=status so the state is announced, not just coloured. */}
        {data.is_void ? (
          <div className="pp-banner no" role="status">
            This invoice has been cancelled. Please contact us with any
            questions.
          </div>
        ) : data.is_paid ? (
          <div className="pp-banner ok" role="status">
            Paid in full. Thank you!
          </div>
        ) : data.is_overdue ? (
          <div className="pp-banner" role="status">
            This invoice is past its due date.
          </div>
        ) : null}

        <header className="present-hero">
          {/* Same logo block the proposal leads with — a customer who approved a
              branded proposal should not receive an unbranded invoice. */}
          {branding.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- workspace-uploaded logo URL
            <img src={branding.logo_url} alt={brandName} className="pp-logo" />
          ) : null}
          <div className="present-eyebrow">Invoice {data.number}</div>
          {data.client_name ? (
            <div className="present-hi">
              Prepared for <strong>{data.client_name}</strong>
            </div>
          ) : null}
          <h1 className="pq-hero-title">{brandName}</h1>
          <div className="present-ornament">
            <div className="present-ornament-line" />
            <div className="present-ornament-diamond" />
            <div className="present-ornament-line r" />
          </div>

          {/* The one number this page exists to communicate. */}
          <div className="inv-due">
            <div className="inv-due-label">
              {data.is_void
                ? "Cancelled"
                : data.is_paid
                  ? "Amount Paid"
                  : "Balance Due"}
            </div>
            <div
              className={`inv-due-amount${data.is_paid && !data.is_void ? " settled" : ""}`}
            >
              {formatCurrency(
                data.is_paid ? data.amount_paid : data.balance_due,
                currency
              )}
            </div>
            {dateLine ? (
              <div
                className={`inv-due-sub${data.is_overdue && !data.is_paid ? " overdue" : ""}`}
              >
                {dateLine}
              </div>
            ) : null}
          </div>
        </header>

        <div className="pq-table-wrap" style={{ marginTop: 48 }}>
          <h2 className="section-heading">Summary</h2>
          <table className="pq-table">
            <caption className="sr-only">
              Line items for invoice {data.number}
            </caption>
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col" className="inv-col-detail">
                  Qty
                </th>
                <th scope="col" className="inv-col-detail">
                  Unit Price
                </th>
                <th scope="col" className="inv-col-detail">
                  Discount
                </th>
                <th scope="col">Amount</th>
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
                    {/* Carries the per-unit detail when the columns collapse
                        on a phone, so nothing is lost at narrow widths. */}
                    <div className="inv-item-meta">
                      {`${item.quantity} \u00d7 ${formatCurrency(item.unit_price, currency)}`}
                      {item.discount
                        ? ` \u00b7 less ${formatCurrency(item.discount, currency)}`
                        : ""}
                    </div>
                  </td>
                  <td className="pq-num inv-col-detail">{item.quantity}</td>
                  <td className="pq-num inv-col-detail">
                    {formatCurrency(item.unit_price, currency)}
                  </td>
                  <td className="pq-num muted inv-col-detail">
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
            {/* Why the balance differs from the total. Without this line a
                credited deposit reads as a pricing mistake. */}
            {hasCredit ? (
              <>
                <div className="pq-total-row credit">
                  <span>Already paid</span>
                  <strong>
                    {"\u2212"}
                    {formatCurrency(data.amount_paid, currency)}
                  </strong>
                </div>
                <div className="pq-total-row grand">
                  <span>Balance due</span>
                  <strong>{formatCurrency(data.balance_due, currency)}</strong>
                </div>
              </>
            ) : null}
          </div>
        </div>

        {/* Pay online */}
        {data.is_paid ? (
          <div className="dep-panel paid">
            <div className="dep-info">
              <div className="dep-label">Paid in Full</div>
              <div className="dep-amount">
                {formatCurrency(data.amount_paid, currency)}
              </div>
            </div>
            <div className="dep-paid-badge">Received &mdash; thank you!</div>
          </div>
        ) : data.is_payable ? (
          <>
            <div className="dep-panel">
              <div className="dep-info">
                <div className="dep-label">Balance Due</div>
                <div className="dep-amount">
                  {formatCurrency(data.balance_due, currency)}
                </div>
                {hasCredit ? (
                  <div className="dep-sub">
                    {formatCurrency(data.amount_paid, currency)} already
                    received
                  </div>
                ) : null}
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
                {checkout.isPending ? "Redirecting\u2026" : "Pay Now"}
              </button>
              {error ? (
                <div className="dep-error" role="alert">
                  {error}
                </div>
              ) : null}
            </div>
            <p className="inv-pay-note">
              You&rsquo;ll be taken to our secure payment page to finish.
            </p>
          </>
        ) : !data.is_void && data.balance_due > 0 ? (
          // Something is owed but online payment isn't available here. Say how
          // to pay instead of showing a button that cannot work.
          <p className="inv-pay-note">
            {contactLine
              ? `To settle this invoice, get in touch \u2014 ${contactLine}`
              : "Please contact us to settle this invoice."}
          </p>
        ) : null}

        {data.notes ? (
          <div className="pp-terms" style={{ marginTop: 48 }}>
            <h2 className="section-heading">Notes</h2>
            <p>{data.notes}</p>
          </div>
        ) : null}
        {data.terms ? (
          <div className="pp-terms">
            <h2 className="section-heading">Terms</h2>
            <p>{data.terms}</p>
          </div>
        ) : null}

        <footer>
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
            <div className="pp-footer-note">
              {renderTextWithLinks(branding.footer)}
            </div>
          ) : null}
        </footer>
      </main>
    </div>
  );
}
