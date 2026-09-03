"use client";

import { useState } from "react";

import "./financing-estimate.css";

export const DEFAULT_FINANCING_DISCLAIMER =
  "Payment figures are estimates for illustration only and are not a financing offer. Financing is subject to application and approval by the provider; actual terms, APR, and payment may vary.";

export interface FinancingPresentationData {
  enabled?: boolean;
  provider: string;
  terms: number[];
  default_term: number;
  apr?: number | null;
  monthly_payment: number;
  monthly_by_term: Record<string, number>;
  headline?: string | null;
  body?: string | null;
  points?: string[];
  disclaimer?: string | null;
}

interface FinancingSnapshotCopy {
  enabled: boolean;
  provider: string;
  terms: number[];
  default_term: number;
  headline?: string | null;
  body?: string | null;
  points?: string[];
  disclaimer?: string | null;
}

/** Adapt the wizard's snapshotted copy to the shared estimate component. */
export function financingFromSnapshot(
  financing: FinancingSnapshotCopy | null | undefined,
  monthlyPayment: number,
  monthlyByTerm: Record<string, number> = {},
): FinancingPresentationData | null {
  if (!financing?.enabled || monthlyPayment <= 0) return null;
  const pricedTerms = financing.terms.filter(
    (term) => (monthlyByTerm[String(term)] ?? 0) > 0,
  );
  return {
    ...financing,
    // Category-only snapshots expose only the default-term grand payment. Do
    // not fabricate alternate-term figures in the browser.
    terms: pricedTerms.length ? pricedTerms : [financing.default_term],
    monthly_payment: monthlyPayment,
    monthly_by_term: monthlyByTerm,
  };
}

interface FinancingEstimateProps {
  financing: FinancingPresentationData | null | undefined;
  /** Compact still renders the full disclaimer beside its one payment figure. */
  variant?: "panel" | "compact";
  className?: string;
}

function paymentFor(
  financing: FinancingPresentationData,
  term: number,
): number {
  const byTerm = financing.monthly_by_term[String(term)];
  return Number.isFinite(byTerm) && byTerm > 0
    ? byTerm
    : financing.monthly_payment;
}

function formatPayment(value: number): string {
  return `$${Math.round(value).toLocaleString("en-US")}`;
}

function formatApr(apr: number | null | undefined): string | null {
  if (apr == null || !Number.isFinite(apr) || apr < 0) return null;
  return `${new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 2,
  }).format(apr)} APR used for this estimate`;
}

/**
 * Shared compliance-safe monthly-payment presentation for wizard, quote, and
 * public proposal surfaces. It never renders a payment without a disclaimer.
 */
export function FinancingEstimate({
  financing,
  variant = "panel",
  className,
}: FinancingEstimateProps) {
  const [chosenTerm, setChosenTerm] = useState<number | null>(null);
  if (
    !financing ||
    financing.enabled === false ||
    !Number.isFinite(financing.monthly_payment) ||
    financing.monthly_payment <= 0
  ) {
    return null;
  }

  const configuredTerms = financing.terms.filter(
    (term) => Number.isInteger(term) && term > 0 && paymentFor(financing, term) > 0,
  );
  const defaultTerm = configuredTerms.includes(financing.default_term)
    ? financing.default_term
    : (configuredTerms[0] ?? financing.default_term);
  const term =
    chosenTerm != null && configuredTerms.includes(chosenTerm)
      ? chosenTerm
      : defaultTerm;
  const payment = paymentFor(financing, term);
  const disclaimer = financing.disclaimer?.trim() || DEFAULT_FINANCING_DISCLAIMER;
  const apr = formatApr(financing.apr);
  const classes = [
    "financing-estimate",
    variant === "compact" ? "financing-estimate--compact" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (variant === "compact") {
    return (
      <aside className={classes} aria-label="Estimated financing payment">
        <div className="financing-estimate__compact-payment">
          <span>Estimated payment</span>
          <strong>{formatPayment(payment)}/month</strong>
        </div>
        <p className="financing-estimate__disclaimer">{disclaimer}</p>
      </aside>
    );
  }

  return (
    <aside className={classes} aria-label="Estimated financing payments">
      <div className="financing-estimate__eyebrow">Payment estimate</div>
      <h2 className="financing-estimate__headline">
        {financing.headline || "A monthly payment may fit your project."}
      </h2>
      <div className="financing-estimate__figure">
        <span>Estimated at</span>
        <strong>{formatPayment(payment)}</strong>
        <span>/month</span>
      </div>
      <div className="financing-estimate__term-copy">
        {term > 0 ? `${term} months` : "Illustrative payment"}
        {apr ? ` · ${apr}` : ""}
      </div>
      {configuredTerms.length > 1 ? (
        <div className="financing-estimate__terms" aria-label="Estimate term">
          {configuredTerms.map((option) => (
            <button
              key={option}
              type="button"
              className={option === term ? "is-active" : undefined}
              aria-pressed={option === term}
              onClick={() => setChosenTerm(option)}
            >
              <span>{option} months</span>
              <strong>{formatPayment(paymentFor(financing, option))}/mo est.</strong>
            </button>
          ))}
        </div>
      ) : null}
      <p className="financing-estimate__body">
        {financing.body || "Illustrative monthly-payment options for this project."}
        {" "}
        <span>Provider: {financing.provider}.</span>
      </p>
      {financing.points?.length ? (
        <ul className="financing-estimate__points">
          {financing.points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      ) : null}
      <p className="financing-estimate__disclaimer">{disclaimer}</p>
    </aside>
  );
}
