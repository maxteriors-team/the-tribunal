"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { PageErrorState } from "@/components/ui/page-state";

export default function OpportunitiesError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <PageErrorState
      message="We couldn't load opportunities. Please try again."
      onRetry={unstable_retry}
    />
  );
}
