"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { SalesWizard } from "@/components/sales-wizard/sales-wizard";
import {
  SERVICE_KEYS,
  type ServiceKey,
} from "@/components/sales-wizard/use-sales-wizard";
import { useWorkspace } from "@/providers/workspace-provider";

/** Resolve `?service=` to a service branch, defaulting to landscape. */
function toService(value: string | null): ServiceKey {
  return SERVICE_KEYS.find((key) => key === value) ?? "landscape";
}

function LoadingWorkspace() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
      Loading workspace…
    </div>
  );
}

function SalesWizardHost() {
  const { currentWorkspace, currentWorkspaceId, isPending } = useWorkspace();
  const searchParams = useSearchParams();
  // A quote covers one service; the Quotes hub deep-links which branch to start.
  const service = toService(searchParams.get("service"));
  const quoteId = searchParams.get("quote");

  return (
    <div className="h-full overflow-y-auto">
      {isPending || !currentWorkspaceId ? (
        <LoadingWorkspace />
      ) : (
        <SalesWizard
          workspaceId={currentWorkspaceId}
          brandName={currentWorkspace?.workspace.name ?? "LL Design"}
          service={service}
          quoteId={quoteId}
        />
      )}
    </div>
  );
}

export default function SalesWizardRoute() {
  return (
    <AppSidebar>
      <Suspense fallback={<LoadingWorkspace />}>
        <SalesWizardHost />
      </Suspense>
    </AppSidebar>
  );
}
