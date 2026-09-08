"use client";

import { useId } from "react";

import type { ProposalSignature } from "@/lib/api/public-proposals";

type SignatureBlockProps = {
  value: ProposalSignature;
  onChange: (next: ProposalSignature) => void;
  /** The cancellation terms shown on this proposal, if the workspace set any. */
  terms: string | null | undefined;
  disabled?: boolean;
  /** Show the unmet requirements. Set once the customer has tried to submit. */
  showErrors?: boolean;
};

/**
 * The e-signature ceremony: a typed name and two separate affirmations.
 *
 * Shared by both proposal views on purpose. Two copies of a legal consent flow
 * drift, and the drift is invisible until a dispute turns on which wording a
 * particular customer actually saw.
 *
 * The two checkboxes are deliberately not combined into one "I agree to
 * everything" box: E-SIGN consent (agreeing to transact electronically) and
 * acknowledging the cancellation terms are distinct disclosures, and a single
 * bundled checkbox is the pattern that gets contracts thrown out.
 */
export function SignatureBlock({
  value,
  onChange,
  terms,
  disabled,
  showErrors,
}: SignatureBlockProps) {
  const nameId = useId();
  const econsentId = useId();
  const cancellationId = useId();
  const errorId = useId();

  const nameMissing = value.signedName.trim().length === 0;
  const showNameError = showErrors && nameMissing;
  const showConsentError = showErrors && !value.econsentAccepted;
  const showCancellationError = showErrors && !value.cancellationAcknowledged;

  return (
    <section className="pp-signature" aria-labelledby={`${nameId}-legend`}>
      <h2 className="section-heading" id={`${nameId}-legend`}>
        Sign to accept
      </h2>

      <div className="pp-signature-field">
        <label htmlFor={nameId}>Type your full name</label>
        <input
          id={nameId}
          type="text"
          autoComplete="name"
          value={value.signedName}
          disabled={disabled}
          aria-invalid={showNameError || undefined}
          aria-describedby={showNameError ? errorId : undefined}
          onChange={(e) => onChange({ ...value, signedName: e.target.value })}
          placeholder="Your full legal name"
        />
        {showNameError ? (
          <p className="pp-signature-error" id={errorId} role="alert">
            Type your full name to sign.
          </p>
        ) : null}
      </div>

      {terms ? (
        <div className="pp-signature-terms">
          {/* The exact text the server snapshots at signing. Rendered in full
              rather than behind a link: an unread linked-away term is the first
              thing challenged in a dispute. */}
          <p>{terms}</p>
        </div>
      ) : null}

      <label className="pp-signature-check" htmlFor={cancellationId}>
        <input
          id={cancellationId}
          type="checkbox"
          checked={value.cancellationAcknowledged}
          disabled={disabled}
          aria-invalid={showCancellationError || undefined}
          onChange={(e) => onChange({ ...value, cancellationAcknowledged: e.target.checked })}
        />
        <span>
          {terms
            ? "I have read and accept the cancellation terms above."
            : "I accept the terms of this proposal."}
          {showCancellationError ? (
            <em className="pp-signature-error" role="alert">
              Please confirm you accept these terms.
            </em>
          ) : null}
        </span>
      </label>

      <label className="pp-signature-check" htmlFor={econsentId}>
        <input
          id={econsentId}
          type="checkbox"
          checked={value.econsentAccepted}
          disabled={disabled}
          aria-invalid={showConsentError || undefined}
          onChange={(e) => onChange({ ...value, econsentAccepted: e.target.checked })}
        />
        <span>
          I agree to sign electronically and to receive this agreement and related records
          electronically.
          {showConsentError ? (
            <em className="pp-signature-error" role="alert">
              Please agree to sign electronically.
            </em>
          ) : null}
        </span>
      </label>

      <p className="pp-signature-legal">
        Signed electronically under the E-SIGN Act and Michigan UETA. We record the time you sign
        and the IP address you sign from, and email you a copy of the signed agreement.
      </p>
    </section>
  );
}

/** True when the ceremony is complete enough to submit. */
export function isSignatureComplete(signature: ProposalSignature): boolean {
  return (
    signature.signedName.trim().length > 0 &&
    signature.econsentAccepted &&
    signature.cancellationAcknowledged
  );
}

export const EMPTY_SIGNATURE: ProposalSignature = {
  signedName: "",
  econsentAccepted: false,
  cancellationAcknowledged: false,
};
