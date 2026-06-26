"use client";

import { Rocket, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
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
 * never completed setup (no AI agent yet), it:
 *
 *  1. force-redirects to /onboarding exactly once per workspace on first
 *     authenticated landing, then
 *  2. renders a dismissible "Finish setting up" card so users who skip can
 *     still find their way back (the persistent sidebar entry is the other half
 *     of discoverability).
 *
 * Returns `null` when the workspace is configured, still loading, or the card
 * has been dismissed.
 */
export function SetupGate() {
  const { isLoading, needsSetup, workspaceId } = useSetupStatus();
  const router = useRouter();
  const pathname = usePathname();
  const [cardHidden, setCardHidden] = useState(false);

  useEffect(() => {
    if (isLoading || !needsSetup || !workspaceId) return;
    // Onboarding itself is not wrapped in this shell, but guard anyway.
    if (pathname.startsWith("/onboarding")) return;
    if (hasAutoRedirectedToOnboarding(workspaceId)) return;

    // Only ever force the redirect once per workspace so a user who skips setup
    // is never trapped bouncing back to the wizard.
    markAutoRedirectedToOnboarding(workspaceId);
    router.replace("/onboarding");
  }, [isLoading, needsSetup, workspaceId, pathname, router]);

  if (
    isLoading ||
    !needsSetup ||
    !workspaceId ||
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
    <div className="border-b bg-gradient-to-r from-yellow-400/10 to-amber-500/10 px-6 py-4">
      <div className="mx-auto flex max-w-5xl items-center gap-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-yellow-400 to-amber-500 text-black shadow-sm">
          <Rocket className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Finish setting up your workspace</p>
          <p className="text-sm text-muted-foreground">
            Connect your CRM and calendar, import leads, and launch your first
            campaign — it only takes a few minutes.
          </p>
        </div>
        <Button asChild size="sm">
          <Link href="/onboarding">
            <Rocket className="size-4" />
            Get started
          </Link>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleDismiss}
          aria-label="Dismiss setup reminder"
        >
          <X className="size-4" />
        </Button>
      </div>
    </div>
  );
}
