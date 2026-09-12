"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { ProviderPageErrorState } from "@/components/shared/provider-error-state";
import { isProviderConfigurationError } from "@/lib/utils/errors";

export default function PeopleSearchError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (!isProviderConfigurationError(error)) {
      Sentry.captureException(error);
    }
  }, [error]);

  return (
    <ProviderPageErrorState
      error={error}
      provider="people-search"
      transientTitle="People search is temporarily unavailable"
      transientMessage="The people-search provider didn't respond. Retry your search."
      reset={reset}
    />
  );
}
