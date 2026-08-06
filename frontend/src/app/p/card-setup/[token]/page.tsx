"use client";

/**
 * Public card-on-file setup page, keyed on a single-use 72-hour token.
 *
 * Its one job is that the customer knowingly authorizes a business to keep and
 * reuse their card. Everything on the page serves that: who is asking (their
 * branding, the same one they saw on the proposal and invoice), who it is for
 * (their first name), what they are agreeing to (the full terms, in readable
 * type, above the card fields), and only then the card itself.
 *
 * An expired or already-used link gets copy that names the fix, not a generic
 * "not found" — the customer did nothing wrong and the remedy is one text
 * message away.
 */

import { useQuery } from "@tanstack/react-query";
import { use } from "react";

import { CardSetupForm } from "@/components/card-setup/card-setup-form";
import { proposalFontVars } from "@/components/proposal/proposal-fonts";
import { PageLoadingState } from "@/components/ui/page-state";
import { publicCardSetupApi } from "@/lib/api/public-card-setup";
import { queryKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils/date";

import "@/components/proposal/proposal-theme.css";
import "@/components/card-setup/card-setup-theme.css";

interface CardSetupPageProps {
  params: Promise<{ token: string }>;
}

export default function CardSetupPage({ params }: CardSetupPageProps) {
  const { token } = use(params);

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.publicCardSetup.byToken(token),
    queryFn: () => publicCardSetupApi.get(token),
    enabled: !!token,
    // A dead link stays dead; retrying just delays the message that helps.
    retry: false,
    // Never cache a single-use setup page across a navigation.
    gcTime: 0,
    staleTime: 0,
  });

  if (isPending) {
    return (
      <div className={`proposal-view card-setup ${proposalFontVars}`}>
        <PageLoadingState className="min-h-screen" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className={`proposal-view card-setup ${proposalFontVars}`}>
        <main className="cs-body">
          <div className="cs-head">
            <div className="cs-eyebrow">Card on file</div>
            <h1 className="cs-title">This link is no longer active</h1>
            <p className="cs-lede">
              Card setup links expire after 72 hours and can only be used once.
              Ask the business to send you a new one and it will work straight
              away.
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className={`proposal-view card-setup ${proposalFontVars}`}>
      <main className="cs-body">
        <header className="cs-head">
          <div className="cs-eyebrow">Card on file</div>
          <h1 className="cs-title">{data.business_name}</h1>
          <p className="cs-lede">
            {`Hi ${data.contact_name} \u2014 ${data.business_name} has asked to keep a card on file so they can bill you for work without needing to chase a payment each time.`}{" "}
            Please read what you&rsquo;re agreeing to below.
          </p>
        </header>

        <CardSetupForm token={token} setup={data} />

        <p className="cs-expiry">
          This link expires {formatDate(data.expires_at)}.
        </p>
      </main>
    </div>
  );
}
