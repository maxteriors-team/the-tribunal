"use client";

/**
 * The customer's card form: Stripe Payment Element plus an explicit opt-in.
 *
 * Three decisions worth knowing about.
 *
 * **The card number never reaches us.** The Payment Element is a Stripe-owned
 * iframe served from `js.stripe.com`; this component sees a confirmation result,
 * not a card. `@stripe/stripe-js` loads that script from Stripe's domain — it is
 * never bundled or self-hosted, which is a hard PCI requirement, not a
 * preference.
 *
 * **The SetupIntent is created on submit, not on load** (Stripe's deferred
 * Elements mode: `mode: "setup"` now, `clientSecret` at confirmation time). The
 * setup link is single-use, so creating the intent when the page opens would
 * burn the link on a page-load — a customer who scrolled away and came back
 * would find a dead link and no card saved. Creating it at the moment they press
 * the button means one intent per genuine attempt.
 *
 * **Consent gates the button, and the version travels with it.** The exact
 * wording version the customer read is posted back and stored on the saved card,
 * so a page left open across a copy change cannot record agreement to terms they
 * never saw.
 */

import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe, type Appearance, type Stripe } from "@stripe/stripe-js";
import { useMemo, useState } from "react";

import { publicCardSetupApi } from "@/lib/api/public-card-setup";
import type { PublicCardSetup } from "@/types/card-setup";

/**
 * Themed to the same tokens as the surrounding page so the iframe does not look
 * pasted on. Values are literals because they cross into a Stripe-hosted frame,
 * where our CSS custom properties do not resolve.
 */
const appearance: Appearance = {
  theme: "night",
  variables: {
    colorPrimary: "#d4af5a",
    colorBackground: "#141414",
    colorText: "#ffffff",
    // Stripe's own muted text; #999 keeps ~6.9:1 on #141414, matching the
    // contrast floor the rest of this page holds to.
    colorTextSecondary: "#999999",
    colorDanger: "#ffb0a4",
    borderRadius: "3px",
    fontSizeBase: "15px",
    spacingUnit: "4px",
  },
};

interface CardSetupFormProps {
  token: string;
  setup: PublicCardSetup;
}

export function CardSetupForm({ token, setup }: CardSetupFormProps) {
  // Loaded once per publishable key. `loadStripe` fetches from js.stripe.com.
  const stripePromise = useMemo<Promise<Stripe | null> | null>(
    () => (setup.publishable_key ? loadStripe(setup.publishable_key) : null),
    [setup.publishable_key]
  );

  if (!stripePromise) {
    // The business has not finished connecting payments. Say so plainly rather
    // than rendering a form that cannot submit.
    return (
      <div className="cs-section">
        <p className="cs-muted" style={{ margin: 0 }}>
          {setup.business_name} isn&rsquo;t set up to accept cards online yet.
          Please get in touch with them directly.
        </p>
      </div>
    );
  }

  return (
    <Elements
      stripe={stripePromise}
      options={{
        // Deferred mode: no SetupIntent exists yet. One is created when the
        // customer submits, which is also when the setup link is spent.
        // ``mode: "setup"`` already means "collect for later use" —
        // ``setupFutureUsage`` is a PaymentIntent option and does not belong here.
        mode: "setup",
        currency: "usd",
        // Cards only. Wallets and redirect methods have different saved-card
        // and off-session semantics that the charge path does not implement.
        paymentMethodTypes: ["card"],
        appearance,
      }}
    >
      <CardFields token={token} setup={setup} />
    </Elements>
  );
}

function CardFields({ token, setup }: CardSetupFormProps) {
  const stripe = useStripe();
  const elements = useElements();

  const [consented, setConsented] = useState(false);
  const [elementReady, setElementReady] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = consented && elementReady && !!stripe && !submitting;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!stripe || !elements || !consented || submitting) return;

    setSubmitting(true);
    setError(null);

    try {
      // Validate the card fields before spending the single-use link on a
      // SetupIntent the customer cannot complete.
      const validation = await elements.submit();
      if (validation.error) {
        setError(validation.error.message ?? "Please check your card details.");
        return;
      }

      const intent = await publicCardSetupApi.createIntent(
        token,
        setup.mandate_text_version
      );

      const result = await stripe.confirmSetup({
        elements,
        clientSecret: intent.client_secret,
        confirmParams: {
          // Only used if the bank sends the customer away to authenticate;
          // they land back here and the page reads the result from the URL.
          return_url: window.location.href,
        },
        redirect: "if_required",
      });

      if (result.error) {
        setError(
          result.error.message ??
            "We couldn't save that card. Please check the details and try again."
        );
        return;
      }
      setSaved(true);
    } catch {
      // The link is single-use, so a failure here usually means it was already
      // spent. Name the fix rather than showing a bare error.
      setError(
        "We couldn't save that card. This link may have expired \u2014 ask " +
          `${setup.business_name} to send a new one.`
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (saved) {
    return (
      <div className="cs-done" role="status">
        <h2 className="cs-done-title">Your card is saved</h2>
        <p className="cs-done-body">
          {setup.business_name} can now charge this card for the work you
          authorized above. You can withdraw that permission at any time by
          contacting them.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <section className="cs-section" aria-labelledby="cs-terms-heading">
        <h2 className="cs-section-title" id="cs-terms-heading">
          What you are authorizing
        </h2>
        <div className="cs-terms">
          {setup.mandate_text.split("\n\n").map((paragraph) => (
            <p key={paragraph.slice(0, 40)}>{paragraph}</p>
          ))}
        </div>

        <label className="cs-consent" htmlFor="cs-consent-check">
          <input
            id="cs-consent-check"
            type="checkbox"
            checked={consented}
            onChange={(e) => setConsented(e.target.checked)}
          />
          <span className="cs-consent-label">
            I have read and agree to these terms, and I authorize{" "}
            {setup.business_name} to save my card and charge it as described.
          </span>
        </label>
      </section>

      <section className="cs-section" aria-labelledby="cs-card-heading">
        <h2 className="cs-section-title" id="cs-card-heading">
          Card details
        </h2>
        <div className="cs-element">
          {!elementReady ? (
            <p className="cs-element-loading">Loading secure card form&hellip;</p>
          ) : null}
          <PaymentElement
            options={{
              layout: "tabs",
              // Wallets off. Link in particular renders its own "save my
              // information" signup with email and phone fields, which puts a
              // second, unrelated consent decision on a page whose entire job
              // is one specific authorization — and its saved credential is
              // Link's, not a payment method this business can charge.
              wallets: { applePay: "never", googlePay: "never", link: "never" },
              // The business's own name, not the platform Stripe account's.
              business: { name: setup.business_name },
            }}
            onReady={() => setElementReady(true)}
          />
        </div>
      </section>

      <button type="submit" className="cs-submit" disabled={!canSubmit}>
        {submitting ? "Saving\u2026" : "Save my card"}
      </button>

      {/* A disabled button with no reason is a dead end, and there are two
          possible reasons. */}
      {!canSubmit && !submitting ? (
        <p className="cs-submit-hint">
          {!elementReady
            ? "Waiting for the secure card form to load\u2026"
            : "Tick the box above to continue."}
        </p>
      ) : null}

      {error ? (
        <div className="cs-error" role="alert">
          {error}
        </div>
      ) : null}

      <p className="cs-secure">
        Your card details go directly to Stripe and are never stored on{" "}
        {setup.business_name}&rsquo;s systems. This link can only be used once.
      </p>
    </form>
  );
}
