"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { ProviderPageErrorState } from "@/components/shared/provider-error-state";
import { isProviderConfigurationError } from "@/lib/utils/errors";

export default function AdLibraryError({
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
      provider="ad-library"
      transientTitle="Ad Library search is temporarily unavailable"
      transientMessage="The ad-library provider didn't respond. Retry your search."
      onRetry={unstable_retry}
    />
  );
}
