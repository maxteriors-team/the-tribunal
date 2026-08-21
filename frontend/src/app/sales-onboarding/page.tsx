import type { Metadata } from "next";
import { Suspense } from "react";

import { SalesRepOnboarding } from "@/components/onboarding/sales-rep-onboarding";

export const metadata: Metadata = {
  title: "Sales Rep Setup | The Tribunal",
};

export default function SalesOnboardingPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-svh items-center justify-center bg-background" role="status">
          <span className="text-sm text-muted-foreground">Loading sales rep setup...</span>
        </div>
      }
    >
      <SalesRepOnboarding />
    </Suspense>
  );
}
