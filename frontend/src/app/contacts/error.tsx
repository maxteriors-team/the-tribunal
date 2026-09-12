"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { PageErrorState } from "@/components/ui/page-state";

export default function ContactsError({
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
      message="We couldn't load contacts. Please try again."
      reset={reset}
    />
  );
}
