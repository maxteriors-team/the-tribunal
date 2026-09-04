"use client";

import { Sparkles, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useIsMounted } from "@/hooks/useMounted";
import { safeGetItem, safeSetItem } from "@/lib/utils/storage";

const DISMISSED_KEY = "crm-announcement-permanent-customer-handoff-v2";

export function ProductUpdateBanner() {
  const mounted = useIsMounted();
  const [dismissed, setDismissed] = useState(false);

  if (!mounted || dismissed || safeGetItem(DISMISSED_KEY) === "dismissed") return null;

  const dismiss = () => {
    safeSetItem(DISMISSED_KEY, "dismissed");
    setDismissed(true);
  };

  return (
    <aside
      role="status"
      aria-label="Product update"
      className="flex shrink-0 items-start gap-3 border-b border-amber-200 bg-amber-50 px-4 py-3 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-100"
    >
      <Sparkles className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold">New: Permanent-lighting projects stay connected</p>
        <p className="text-amber-900/80 dark:text-amber-100/80">
          Save designs to a customer, send a price range, and carry the approved mockup and design
          into the job. Approvals and deposits still use the exact estimate.
        </p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="-my-1 -mr-2 size-8 shrink-0 text-current hover:bg-amber-200/60 hover:text-current dark:hover:bg-amber-900/60"
        onClick={dismiss}
        aria-label="Dismiss product update"
      >
        <X className="size-4" aria-hidden />
      </Button>
    </aside>
  );
}
