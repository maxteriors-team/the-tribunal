"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { PageErrorState } from "@/components/ui/page-state";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <PageErrorState
      className="min-h-[400px]"
      message={
        error.digest
          ? `An unexpected error occurred. Please try again or refresh the page. (Error ID: ${error.digest})`
          : "An unexpected error occurred. Please try again or refresh the page."
      }
      reset={reset}
    />
  );
}
