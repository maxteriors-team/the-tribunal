"use client";

import { AlertCircle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { PublicReferralPartnerIntake } from "@/components/referral-partners/public-referral-partner-intake";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const INTAKE_TOKEN_STORAGE_KEY = "referral-partner-intake-token";
const SAFE_TOKEN_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

type CapabilityState = string | null | undefined;

export default function ReferralPartnerIntakePage() {
  const [capability, setCapability] = useState<CapabilityState>(undefined);

  useEffect(() => {
    const fragment = window.location.hash;
    let token: string | null = null;

    if (fragment) {
      // Remove the capability from browser UI, copied URLs, and client telemetry
      // before starting any API request. Fragments are never sent over HTTP.
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${window.location.search}`,
      );

      const candidate = new URLSearchParams(fragment.slice(1)).get("token")?.trim() ?? "";
      if (candidate && SAFE_TOKEN_PATTERN.test(candidate)) {
        token = candidate;
        try {
          window.sessionStorage.setItem(INTAKE_TOKEN_STORAGE_KEY, candidate);
        } catch {
          // Storage can be unavailable in hardened browsers; this visit still works.
        }
      } else {
        try {
          window.sessionStorage.removeItem(INTAKE_TOKEN_STORAGE_KEY);
        } catch {
          // Nothing else to clear when session storage is unavailable.
        }
      }
    } else {
      try {
        const stored = window.sessionStorage.getItem(INTAKE_TOKEN_STORAGE_KEY);
        token = stored && SAFE_TOKEN_PATTERN.test(stored) ? stored : null;
      } catch {
        token = null;
      }
    }

    const timer = window.setTimeout(() => setCapability(token), 0);
    return () => window.clearTimeout(timer);
  }, []);

  if (capability === undefined) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4 py-12">
        <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="size-5 animate-spin" aria-hidden />
          Opening your profile form…
        </div>
      </main>
    );
  }

  if (!capability) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4 py-12">
        <Card className="w-full max-w-lg text-center">
          <CardHeader>
            <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-destructive/10">
              <AlertCircle className="size-6 text-destructive" aria-hidden />
            </div>
            <CardTitle>This intake link is invalid</CardTitle>
            <CardDescription>
              Ask your contact for a new referral-partner intake link and open the complete link
              they send you.
            </CardDescription>
          </CardHeader>
        </Card>
      </main>
    );
  }

  return <PublicReferralPartnerIntake capability={capability} />;
}
