"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CreditCard, CheckCircle2, Zap, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { createCheckout, createPortal, getBillingStatus, type BillingStatus } from "@/lib/api/billing";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

// ─── Constants ────────────────────────────────────────────────────────────────

const PLAN_PRICE = process.env.NEXT_PUBLIC_PLAN_PRICE ?? "$297/month";

const PLAN_FEATURES = [
  "AI-powered SMS agent that texts your dead leads",
  "Automatic appointment booking directly on your Cal.com calendar",
  "Unlimited lead uploads via CSV",
  "Smart follow-up sequences — 2-touch cadence, fully automated",
  "Realtor-focused messaging templates designed to get replies",
];

// ─── Sub-components ───────────────────────────────────────────────────────────

function PlanFeature({ text }: { text: string }) {
  return (
    <li className="flex items-start gap-3">
      <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-green-500" />
      <span className="text-sm text-muted-foreground">{text}</span>
    </li>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

function BillingContent() {
  const router = useRouter();
  const [isRedirecting, setIsRedirecting] = React.useState(false);

  const { data: billingStatus, isPending } = useQuery<BillingStatus>({
    queryKey: queryKeys.billing.status(),
    queryFn: getBillingStatus,
    retry: false,
  });

  const subscribed = billingStatus?.subscribed ?? false;

  async function handleGetStarted() {
    setIsRedirecting(true);
    try {
      const { checkout_url } = await createCheckout();
      window.location.href = checkout_url;
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Failed to start checkout. Please try again."));
      setIsRedirecting(false);
    }
  }

  async function handleManageSubscription() {
    setIsRedirecting(true);
    try {
      const { portal_url } = await createPortal();
      window.location.href = portal_url;
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Failed to open billing portal. Please try again."));
      setIsRedirecting(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-8 p-6 md:p-12 max-w-2xl mx-auto w-full">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="flex justify-center">
          <div className="rounded-full bg-primary/10 p-4">
            <Zap className="h-8 w-8 text-primary" />
          </div>
        </div>
        <h1 className="text-3xl font-bold tracking-tight">
          Realtor Lead Reactivation
        </h1>
        <p className="text-muted-foreground max-w-md mx-auto">
          Let AI text your cold leads, provide value, and book appointments on your
          calendar — automatically.
        </p>
      </div>

      {/* Pricing Card */}
      <Card className="w-full border-2 border-primary/20">
        <CardHeader className="pb-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-xl">Monthly Subscription</CardTitle>
            {subscribed && (
              <Badge className="bg-green-100 text-green-800 hover:bg-green-100 dark:bg-green-900/30 dark:text-green-400">
                Active
              </Badge>
            )}
          </div>
          <div className="flex items-baseline gap-1 mt-1">
            <span className="text-4xl font-bold">{PLAN_PRICE.split("/")[0]}</span>
            {PLAN_PRICE.includes("/") && (
              <span className="text-muted-foreground text-sm">
                /{PLAN_PRICE.split("/")[1]}
              </span>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {/* Feature list */}
          <ul className="space-y-3">
            {PLAN_FEATURES.map((feature) => (
              <PlanFeature key={feature} text={feature} />
            ))}
          </ul>

          {/* CTA button */}
          {isPending ? (
            <Button className="w-full" disabled>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading…
            </Button>
          ) : subscribed ? (
            <div className="space-y-3">
              <p className="text-sm text-center text-muted-foreground">
                You have an active subscription.
              </p>
              <Button
                variant="outline"
                className="w-full"
                onClick={handleManageSubscription}
                disabled={isRedirecting}
              >
                {isRedirecting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <CreditCard className="mr-2 h-4 w-4" />
                )}
                Manage Subscription
              </Button>
              <Button
                className="w-full"
                variant="secondary"
                onClick={() => router.push("/realtor-dashboard")}
              >
                Go to Dashboard
              </Button>
            </div>
          ) : (
            <Button
              className="w-full"
              size="lg"
              onClick={handleGetStarted}
              disabled={isRedirecting}
            >
              {isRedirecting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CreditCard className="mr-2 h-4 w-4" />
              )}
              Get Started
            </Button>
          )}

          {/* Fine print */}
          {!subscribed && (
            <p className="text-xs text-center text-muted-foreground">
              Secure payment via Stripe. Cancel anytime.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function BillingPage() {
  return (
    <AppSidebar>
      <BillingContent />
    </AppSidebar>
  );
}
