"use client";

import { ListChecks } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { useIsMounted } from "@/hooks/useMounted";
import {
  hasAutoRedirectedToSalesRepOnboarding,
  hasCompletedSalesRepOnboarding,
  markAutoRedirectedToSalesRepOnboarding,
} from "@/lib/sales-rep-onboarding-status";
import { useAuth } from "@/providers/auth-provider";
import { useWorkspace } from "@/providers/workspace-provider";

export function SalesRepOnboardingGate() {
  const router = useRouter();
  const mounted = useIsMounted();
  const { user, isLoading: authLoading } = useAuth();
  const { currentWorkspace, currentWorkspaceId, isPending: workspacePending } = useWorkspace();

  const isReady = mounted && !authLoading && !workspacePending;
  const isSalesRep = currentWorkspace?.role === "sales_rep";
  const userId = user?.id;
  const hasIdentity = userId !== undefined && currentWorkspaceId !== null;
  const isComplete =
    isReady && isSalesRep && hasIdentity
      ? hasCompletedSalesRepOnboarding(userId, currentWorkspaceId)
      : false;

  useEffect(() => {
    if (!isReady || !isSalesRep || !hasIdentity || isComplete) return;
    if (hasAutoRedirectedToSalesRepOnboarding(userId, currentWorkspaceId)) return;

    markAutoRedirectedToSalesRepOnboarding(userId, currentWorkspaceId);
    router.replace("/sales-onboarding");
  }, [currentWorkspaceId, hasIdentity, isComplete, isReady, isSalesRep, router, userId]);

  if (!isReady || !isSalesRep || !hasIdentity || isComplete) return null;

  return (
    <aside className="border-b bg-card px-4 py-3 sm:px-6" aria-label="Sales rep setup reminder">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 sm:flex-row sm:items-center">
        <ListChecks className="hidden size-5 shrink-0 text-primary sm:block" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">Finish your sales rep setup</p>
          <p className="text-sm text-muted-foreground">
            Confirm your profile, connect your calendar, and learn the first-lead workflow.
          </p>
        </div>
        <Button asChild size="sm" className="w-full shrink-0 sm:w-auto">
          <Link href="/sales-onboarding">Continue setup</Link>
        </Button>
      </div>
    </aside>
  );
}
