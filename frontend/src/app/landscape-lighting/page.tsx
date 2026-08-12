"use client";

/** Customer-linked landscape lighting project dashboard. */
import { LightingProjectsPage } from "@/components/landscape-lighting/lighting-projects-page";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { PageEmptyState, PageLoadingState } from "@/components/ui/page-state";
import { useWorkspace } from "@/providers/workspace-provider";

export default function LandscapeLightingPage() {
  const { currentWorkspaceId, isPending } = useWorkspace();

  return (
    <AppSidebar>
      {isPending ? (
        <PageLoadingState className="h-full" message="Opening lighting projects..." />
      ) : currentWorkspaceId ? (
        <LightingProjectsPage workspaceId={currentWorkspaceId} />
      ) : (
        <PageEmptyState
          className="h-full"
          title="Choose a workspace"
          description="Select a workspace before opening landscape lighting projects."
        />
      )}
    </AppSidebar>
  );
}
