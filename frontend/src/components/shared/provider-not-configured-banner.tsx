"use client";

import { AlertTriangle } from "lucide-react";
import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useCapabilities } from "@/hooks/useCapabilities";

/**
 * Actionable banner shown when a lead-gen feature depends on an external
 * provider key that is not configured.
 *
 * Rendered in place of a generic "search failed" toast or a silent empty state
 * so the user understands *why* nothing is happening and where to fix it. Pair
 * with the backend's `provider_not_configured` / `ad_library_provider_unavailable`
 * error codes (see `getApiErrorCode`).
 */
export function ProviderNotConfiguredBanner({
  title,
  description,
  restrictedDescription = "Ask a workspace owner or admin to configure this integration.",
  settingsHref = "/settings?tab=integrations",
  settingsLabel = "Open Settings",
}: {
  title: string;
  description: string;
  restrictedDescription?: string;
  settingsHref?: string;
  settingsLabel?: string;
}) {
  const { can } = useCapabilities();
  const canConfigureIntegrations = can("workspace:manage");
  return (
    <Alert>
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-muted-foreground">
          {canConfigureIntegrations ? description : restrictedDescription}
        </span>
        {canConfigureIntegrations ? (
          <Button variant="outline" size="sm" asChild className="shrink-0">
            <Link href={settingsHref}>{settingsLabel}</Link>
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
