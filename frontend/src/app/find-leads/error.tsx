"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { ProviderPageErrorState } from "@/components/shared/provider-error-state";
import { isProviderConfigurationError } from "@/lib/utils/errors";

export default function FindLeadsError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    if (!isProviderConfigurationError(error)) {
      Sentry.captureException(error);
    }
  }, [error]);

  return (
    <ProviderPageErrorState
      error={error}
      provider="scraping"
      transientTitle="Lead search is temporarily unavailable"
      transientMessage="The scraping provider didn't respond. Retry your lead search."
      onRetry={unstable_retry}
    />
  );
}
