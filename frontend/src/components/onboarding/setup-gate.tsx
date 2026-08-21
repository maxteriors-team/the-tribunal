"use client";

import { Rocket, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useSetupStatus } from "@/hooks/useSetupStatus";
import {
  dismissSetupCard,
  hasAutoRedirectedToOnboarding,
  isSetupCardDismissed,
  markAutoRedirectedToOnboarding,
} from "@/lib/onboarding-status";

/**
 * First-run onboarding gate (finding RF-002).
 *
 * Rendered inside the authenticated app shell. When the current workspace has
 * never completed setup (no `onboarding_completed_at` stamp — never "has no AI
 * agent", which is true of workspaces the system seeded an agent for at creation
 * time) *and the caller may configure the workspace*, it:
 *
 *  1. force-redirects to /onboarding exactly once per workspace on first
 *     authenticated landing, then
 *  2. renders a dismissible "Finish setting up" card so users who skip can
 *     still find their way back (the persistent sidebar entry is the other half
 *     of discoverability).
 *
 * Setup is an owner/admin job (team calendar setup, lead import, launching the
 * first campaign), so everything here is gated on `workspace:manage` — mirroring
 * the backend gate. Without it a field technician was force-redirected into the
 * owner wizard on first login and shown workspace-setup UI on every page.
 *
 * Returns `null` when the workspace is configured, still loading, the caller
 * cannot manage the workspace, or the card has been dismissed.
 */
export function SetupGate() {
  const { isLoading, needsSetup, workspaceId } = useSetupStatus();
  const { can } = useCapabilities();
  const canManageWorkspace = can("workspace:manage");
  const router = useRouter();
  const pathname = usePathname();
  const [cardHidden, setCardHidden] = useState(false);

  useEffect(() => {
    // `isLoading` covers the workspace probe, so the membership role (and with
    // it `canManageWorkspace`) has resolved by the time we get past it. The tier
    // fails closed to "field" while loading, so acting earlier would bounce a
    // real owner/admin away from setup mid-load.
    if (isLoading || !needsSetup || !workspaceId) return;
    // Never drag a member who cannot configure the workspace (field technicians
    // and other non-admin tiers) into the owner setup wizard.
    if (!canManageWorkspace) return;
    // Onboarding itself is not wrapped in this shell, but guard anyway.
    if (pathname.startsWith("/onboarding")) return;
    if (hasAutoRedirectedToOnboarding(workspaceId)) return;

    // Only ever force the redirect once per workspace so a user who skips setup
    // is never trapped bouncing back to the wizard.
    markAutoRedirectedToOnboarding(workspaceId);
    router.replace("/onboarding");
  }, [isLoading, needsSetup, workspaceId, canManageWorkspace, pathname, router]);

  if (
    isLoading ||
    !needsSetup ||
    !workspaceId ||
    !canManageWorkspace ||
    cardHidden ||
    isSetupCardDismissed(workspaceId)
  ) {
    return null;
  }

  const handleDismiss = () => {
    dismissSetupCard(workspaceId);
    setCardHidden(true);
  };

  return (
    <div className="border-b bg-gradient-to-r from-yellow-400/10 to-amber-500/10 px-4 py-4 sm:px-6">
      <div className="mx-auto grid max-w-5xl grid-cols-[auto_1fr_auto] items-start gap-x-3 gap-y-3 sm:flex sm:items-center sm:gap-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-yellow-400 to-amber-500 text-black shadow-sm">
          <Rocket className="size-5" />
        </div>
        <div className="min-w-0 sm:flex-1">
          <p className="font-semibold">Finish setting up your workspace</p>
          <p className="text-sm text-muted-foreground">
            Connect your CRM and calendar, import leads, and launch your first campaign — it only
            takes a few minutes.
          </p>
        </div>
        <Button asChild size="sm" className="col-start-2 row-start-2 justify-self-start">
          <Link href="/onboarding">
            <Rocket className="size-4" />
            Get started
          </Link>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="col-start-3 row-start-1"
          onClick={handleDismiss}
          aria-label="Dismiss setup reminder"
        >
          <X className="size-4" />
        </Button>
      </div>
    </div>
  );
}
