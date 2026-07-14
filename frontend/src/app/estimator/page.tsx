"use client";

import { RooflineEstimator } from "@/components/estimator/roofline-estimator";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { useWorkspace } from "@/providers/workspace-provider";

export default function EstimatorRoute() {
  const { currentWorkspaceId, isPending } = useWorkspace();

  return (
    <AppSidebar>
      <div className="h-full overflow-y-auto">
        {isPending || !currentWorkspaceId ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Loading workspace…
          </div>
        ) : (
          <RooflineEstimator workspaceId={currentWorkspaceId} />
        )}
      </div>
    </AppSidebar>
  );
}
