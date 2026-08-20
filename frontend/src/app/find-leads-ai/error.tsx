"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { ProviderPageErrorState } from "@/components/shared/provider-error-state";
import { isProviderConfigurationError } from "@/lib/utils/errors";

export default function FindLeadsAiError({
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
      provider="openai"
      transientTitle="AI lead discovery is temporarily unavailable"
      transientMessage="OpenAI or the lead-search provider didn't respond. Retry your request."
      onRetry={unstable_retry}
    />
  );
}
