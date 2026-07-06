"use client";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { SalesWizard } from "@/components/sales-wizard/sales-wizard";
import { useWorkspace } from "@/providers/workspace-provider";

export default function SalesWizardRoute() {
  const { currentWorkspace, currentWorkspaceId, isPending } = useWorkspace();

  return (
    <AppSidebar>
      <div className="h-full overflow-y-auto">
        {isPending || !currentWorkspaceId ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Loading workspace…
          </div>
        ) : (
          <SalesWizard
            workspaceId={currentWorkspaceId}
            brandName={currentWorkspace?.workspace.name ?? "LL Design"}
          />
        )}
      </div>
    </AppSidebar>
  );
}
