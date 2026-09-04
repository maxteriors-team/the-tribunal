"use client";

import { ExternalLink } from "lucide-react";

import type { PublicProposal } from "@/types/proposal";

import { DepositPanel } from "./deposit-panel";
import { fmt, GREEN_SKY_APPLICATION_URL, type ProposalGreenSkyView } from "./document";

const GREEN_SKY_DISCLOSURES_URL = "https://www.greensky.com/disclosures/";

interface PermanentPaymentOptionsProps {
  data: PublicProposal;
  program: ProposalGreenSkyView;
  projectPrice: number;
  depositAmount?: number | null;
  busy?: boolean;
}

export function PermanentPaymentOptions({
  data,
  program,
  projectPrice,
  depositAmount,
  busy = false,
}: PermanentPaymentOptionsProps) {
  const due = depositAmount === undefined ? (data.deposit_amount ?? 0) : (depositAmount ?? 0);
  const hasDeposit = due > 0;
  const accepted = data.status === "approved";
  const closed = data.is_expired || data.status === "declined";
  const canApply = !closed && !data.deposit_paid;
  const apr = Number.isInteger(program.apr_percent)
    ? String(program.apr_percent)
    : program.apr_percent.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");

  return (
    <section
      id="permanent-payment-options"
      className="permanent-payment-options"
      aria-labelledby="permanent-payment-heading"
    >
      <div className="permanent-payment-intro">
        <h2 className="section-heading" id="permanent-payment-heading">
          Choose how to move forward
        </h2>
        <div className="permanent-payment-price">{fmt(projectPrice)}</div>
        <p>
          One project price. It stays the same whether you pay the deposit or explore GreenSky
          financing.
        </p>
      </div>

      <div className="permanent-payment-grid">
        <article className="permanent-payment-card" aria-labelledby="deposit-option-heading">
          <div className="permanent-payment-kicker">Deposit</div>
          <h3 id="deposit-option-heading">Accept, then pay securely</h3>
          {hasDeposit ? (
            <>
              <div className="permanent-payment-amount">{fmt(due)} due</div>
              <p>
                First accept the proposal below. Your recorded acceptance unlocks the existing
                secure Stripe checkout.
              </p>
              {data.deposit_paid ? (
                <div className="permanent-payment-status">Deposit received — thank you.</div>
              ) : closed ? (
                <div className="permanent-payment-status">
                  This proposal is no longer open for payment.
                </div>
              ) : accepted ? (
                <div className="permanent-payment-action no-print">
                  <DepositPanel data={data} amountDue={due} busy={busy} />
                </div>
              ) : (
                <a className="cta-btn-primary no-print" href="#proposal-response">
                  Review and accept proposal
                </a>
              )}
            </>
          ) : (
            <>
              <div className="permanent-payment-amount">No online deposit</div>
              <p>No deposit is configured for this proposal. Acceptance is still recorded below.</p>
            </>
          )}
        </article>

        <article className="permanent-payment-card" aria-labelledby="greensky-option-heading">
          <div className="permanent-payment-kicker">GreenSky financing</div>
          <h3 id="greensky-option-heading">
            {apr}% APR for {program.term_months} months
          </h3>
          <p>{program.offer_details}</p>

          <dl className="permanent-payment-identifiers">
            <div>
              <dt>Merchant number</dt>
              <dd>{program.merchant_number}</dd>
            </div>
            <div>
              <dt>Plan number</dt>
              <dd>{program.plan_number}</dd>
            </div>
          </dl>

          <ol className="permanent-payment-steps">
            <li>Open GreenSky&apos;s official application in a separate tab.</li>
            <li>Enter the merchant and plan numbers above when GreenSky asks.</li>
            <li>Submit financial information directly to GreenSky, not Tribunal.</li>
          </ol>

          {canApply ? (
            <a
              className="cta-btn-secondary permanent-payment-link no-print"
              href={GREEN_SKY_APPLICATION_URL}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
              aria-label="Start GreenSky application (opens in a new tab)"
            >
              Start GreenSky application
              <ExternalLink aria-hidden="true" />
            </a>
          ) : (
            <div className="permanent-payment-status">
              {data.deposit_paid
                ? "A deposit has been paid, so this application action is no longer offered."
                : "This proposal is no longer open for an application referral."}
            </div>
          )}

          <p className="permanent-payment-disclosure">
            {program.disclosure}{" "}
            <a
              href={GREEN_SKY_DISCLOSURES_URL}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
              aria-label="Read GreenSky disclosures (opens in a new tab)"
            >
              Read GreenSky disclosures.
            </a>
          </p>
        </article>
      </div>
    </section>
  );
}
