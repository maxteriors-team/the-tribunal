import type { Metadata } from "next";

import { PaymentStatusCard } from "./payment-status-card";

export const metadata: Metadata = {
  title: "Payment status",
  robots: { index: false },
};

/**
 * Stripe Checkout return page. It never renders a success claim until the
 * backend verifies the Checkout Session supplied by Stripe.
 */
export default async function PaymentCompletePage({
  searchParams,
}: {
  searchParams: Promise<{ session_id?: string | string[] }>;
}) {
  const rawSessionId = (await searchParams).session_id;
  const sessionId =
    typeof rawSessionId === "string" && rawSessionId.length > 0 ? rawSessionId : null;

  return <PaymentStatusCard key={sessionId ?? "missing"} sessionId={sessionId} />;
}
