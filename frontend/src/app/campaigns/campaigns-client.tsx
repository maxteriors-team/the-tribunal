"use client";

import { CampaignsList } from "@/components/campaigns/campaigns-list";
import { useWorkspaceId } from "@/hooks/use-workspace-id";

export function CampaignsClient() {
  const workspaceId = useWorkspaceId();
  // Key prop forces remount when workspace changes, resetting all local state
  return <CampaignsList key={workspaceId} />;
}
