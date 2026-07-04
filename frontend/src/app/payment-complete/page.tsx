import { CheckCircle2 } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Payment received",
  robots: { index: false },
};

/**
 * Stripe Checkout success landing page. Customers (not operators) arrive here
 * after paying an invoice or in-call payment link, so it's public and rendered
 * on an explicit light surface — independent of the operator app theme.
 */
export default function PaymentCompletePage() {
  return (
    <main className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-lg border border-slate-200 p-8 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
          <CheckCircle2 className="h-9 w-9 text-green-600" />
        </div>
        <h1 className="mt-6 text-2xl font-bold text-slate-900">
          Payment received
        </h1>
        <p className="mt-3 text-slate-600">
          Thank you! Your payment has been processed successfully.
        </p>
        <p className="mt-2 text-sm text-slate-500">
          A receipt is on its way to your email. You can safely close this
          page.
        </p>
      </div>
    </main>
  );
}
