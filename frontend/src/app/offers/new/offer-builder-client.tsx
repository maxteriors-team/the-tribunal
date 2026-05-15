"use client";

import { OfferBuilderWizard } from "@/components/offers/offer-builder-wizard";
import { useWorkspaceId } from "@/hooks/use-workspace-id";

export function OfferBuilderClient() {
  const workspaceId = useWorkspaceId();
  return <OfferBuilderWizard workspaceId={workspaceId!} />;
}
