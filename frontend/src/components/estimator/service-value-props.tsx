"use client";

/**
 * What the homeowner reads about each service they're being sold.
 *
 * One block per selected service, each arguing in its own terms: landscape
 * leads with nightly curb appeal and safety, permanent with never touching a
 * ladder again, Christmas with a low-commitment season. A three-service quote
 * that shows one generic list is how a customer ends up thinking they bought
 * one thing — so these never merge.
 *
 * Copy comes from the workspace pricing config (operator-editable); this
 * component only arranges it. No prices here — the comparison card owns money.
 */
import { Check } from "lucide-react";

import {
  SERVICES,
  serviceValueProps,
  type ServiceKey,
} from "@/lib/estimator/services";
import type { PricingSettings } from "@/types/sales-wizard";

import "./service-value-props.css";

interface ServiceValuePropsProps {
  services: readonly ServiceKey[];
  pricing: PricingSettings | null | undefined;
  /** Package being quoted, so landscape leads with that package's own points. */
  tierKey?: string | null;
}

export function ServiceValueProps({
  services,
  pricing,
  tierKey,
}: ServiceValuePropsProps) {
  const shown = SERVICES.filter((spec) => services.includes(spec.key));
  if (shown.length === 0) return null;

  return (
    <section className="svp" aria-label="What's included">
      <h2 className="svp-title">
        {shown.length > 1 ? "Your complete lighting plan" : shown[0].headline}
      </h2>
      <div
        className="svp-grid"
        data-count={Math.min(shown.length, 3)}
      >
        {shown.map((spec) => {
          const points = serviceValueProps(spec.key, pricing, tierKey);
          return (
            <article className="svp-card" key={spec.key}>
              <header className="svp-card-head">
                <span className="svp-eyebrow">{spec.label}</span>
                <h3 className="svp-headline">{spec.headline}</h3>
                <p className="svp-summary">{spec.summary}</p>
              </header>
              <ul className="svp-points">
                {points.map((point) => (
                  <li key={point}>
                    <Check className="svp-check" aria-hidden="true" />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
    </section>
  );
}
