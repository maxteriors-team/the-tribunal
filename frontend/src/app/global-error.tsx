"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { PageErrorState } from "@/components/ui/page-state";

export default function GlobalError({
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
    <html lang="en">
      <body className="bg-background">
        <PageErrorState
          className="min-h-screen"
          message={
            error.digest
              ? `An unexpected error occurred. Please try again or refresh the page. (Error ID: ${error.digest})`
              : "An unexpected error occurred. Please try again or refresh the page."
          }
          reset={reset}
        />
      </body>
    </html>
  );
}
