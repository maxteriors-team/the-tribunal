"use client";

import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import Link from "next/link";

import { Button } from "@/components/ui/button";

/** Retry a failed route without clearing cached data or reloading the app. */
export function RouteErrorActions({ reset }: { reset: () => void }) {
  const { reset: resetQueries } = useQueryErrorResetBoundary();

  return (
    <div className="flex flex-wrap justify-center gap-3">
      <Button
        type="button"
        variant="outline"
        className="min-h-11 hover:scale-100 active:scale-100"
        onClick={() => {
          // Next only resets its render error; React Query must allow a refetch too.
          resetQueries();
          reset();
        }}
      >
        Try again
      </Button>
      <Button asChild variant="ghost" className="min-h-11 hover:scale-100 active:scale-100">
        <Link href="/" prefetch={false}>
          Back to app
        </Link>
      </Button>
    </div>
  );
}
