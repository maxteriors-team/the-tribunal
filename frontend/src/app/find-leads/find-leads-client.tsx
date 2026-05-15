"use client";

import { FindLeadsPage } from "@/components/contacts/find-leads-page";
import { useWorkspaceId } from "@/hooks/use-workspace-id";

export function FindLeadsClient() {
  const workspaceId = useWorkspaceId();
  return <FindLeadsPage key={workspaceId} />;
}
