"use client";

import { ExperimentsList } from "@/components/experiments/experiments-list";
import { useWorkspaceId } from "@/hooks/use-workspace-id";

export function ExperimentsClient() {
  const workspaceId = useWorkspaceId();
  // Key prop forces remount when workspace changes, resetting all local state
  return <ExperimentsList key={workspaceId} />;
}
