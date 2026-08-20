"use client";

import { CheckCircle2, Clock3, LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { publicPaymentsApi, type PublicPaymentStatus } from "@/lib/api/public-payments";

type PaymentViewState = PublicPaymentStatus | "checking" | "missing";

interface PaymentStatusCardProps {
  sessionId: string | null;
}

const stateCopy: Record<PaymentViewState, { title: string; description: string; detail: string }> =
  {
    checking: {
      title: "Checking payment",
      description: "Confirming this Checkout session with Stripe.",
      detail: "Please keep this page open for a moment.",
    },
    paid: {
      title: "Payment received",
      description: "Stripe confirmed your payment successfully.",
      detail: "You can safely close this page.",
    },
    pending: {
      title: "Payment processing",
      description: "Stripe has not confirmed this payment yet.",
      detail: "Wait a moment, then check the payment again.",
    },
    expired: {
      title: "Payment link expired",
      description: "No payment was confirmed for this Checkout session.",
      detail: "Ask the business for a new payment link.",
    },
    failed: {
      title: "We couldn't verify this payment",
      description: "The link may be invalid, or Stripe may be temporarily unavailable.",
      detail: "Try checking again before starting another payment.",
    },
    missing: {
      title: "Payment not verified",
      description: "This page needs the Checkout session from Stripe.",
      detail: "Open the complete return link from your payment flow.",
    },
  };

function StatusIcon({ state }: { state: PaymentViewState }) {
  const wrapperClass =
    state === "paid"
      ? "bg-green-100"
      : state === "checking" || state === "pending"
        ? "bg-blue-100"
        : "bg-amber-100";

  return (
    <div
      className={`mx-auto flex h-16 w-16 items-center justify-center rounded-full ${wrapperClass}`}
      aria-hidden="true"
    >
      {state === "paid" ? (
        <CheckCircle2 className="h-9 w-9 text-green-600" />
      ) : state === "checking" ? (
        <LoaderCircle className="h-9 w-9 animate-spin text-blue-600" />
      ) : state === "pending" ? (
        <Clock3 className="h-9 w-9 text-blue-600" />
      ) : (
        <TriangleAlert className="h-9 w-9 text-amber-600" />
      )}
    </div>
  );
}

export function PaymentStatusCard({ sessionId }: PaymentStatusCardProps) {
  const [attempt, setAttempt] = useState(0);
  const [viewState, setViewState] = useState<PaymentViewState>(sessionId ? "checking" : "missing");

  useEffect(() => {
    if (!sessionId) {
      return;
    }

    const controller = new AbortController();
    void publicPaymentsApi
      .verify(sessionId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setViewState(result.status);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setViewState("failed");
        }
      });

    return () => controller.abort();
  }, [attempt, sessionId]);

  const copy = stateCopy[viewState];
  const canRetry = viewState === "failed" || viewState === "pending";

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <section
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-lg"
        aria-live="polite"
        aria-busy={viewState === "checking"}
      >
        <StatusIcon state={viewState} />
        <h1 className="mt-6 text-2xl font-bold text-slate-900">{copy.title}</h1>
        <p className="mt-3 text-slate-600">{copy.description}</p>
        <p className="mt-2 text-sm text-slate-500">{copy.detail}</p>

        {canRetry ? (
          <button
            type="button"
            className="mx-auto mt-6 inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2"
            onClick={() => {
              setViewState("checking");
              setAttempt((value) => value + 1);
            }}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {viewState === "pending" ? "Check again" : "Try again"}
          </button>
        ) : null}
      </section>
    </main>
  );
}
