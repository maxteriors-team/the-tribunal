import { XCircle } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Payment not completed",
  robots: { index: false },
};

/**
 * Stripe Checkout cancel landing page. Public, customer-facing, light surface
 * — see payment-complete/page.tsx for the convention.
 */
export default function PaymentCancelledPage() {
  return (
    <main className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-lg border border-slate-200 p-8 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-amber-100">
          <XCircle className="h-9 w-9 text-amber-600" />
        </div>
        <h1 className="mt-6 text-2xl font-bold text-slate-900">
          Payment not completed
        </h1>
        <p className="mt-3 text-slate-600">
          Your payment was cancelled and you have not been charged.
        </p>
        <p className="mt-2 text-sm text-slate-500">
          To try again, reopen the payment link from your invoice email or
          text message.
        </p>
      </div>
    </main>
  );
}
