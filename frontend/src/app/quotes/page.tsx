"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Cable,
  Calculator,
  ChevronDown,
  ClipboardCopy,
  FileText,
  Ruler,
  Snowflake,
  Trees,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { LightDesigner } from "@/components/estimator/light-designer";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { CopyToJobTab } from "@/components/quotes/copy-to-job-tab";
import { QuotesList } from "@/components/quotes/quotes-list";
import type { ServiceKey } from "@/components/sales-wizard/use-sales-wizard";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { PageLoadingState } from "@/components/ui/page-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import { useWorkspace } from "@/providers/workspace-provider";
import type { PricingSettings } from "@/types/sales-wizard";

// Deep-linkable tabs so the command palette / `/estimator` redirect can land the
// rep straight on the Light Designer (`?tab=designer`).
const TAB_VALUES = new Set(["quotes", "designer", "copy-to-job"]);

// A quote covers one service, so the branch is chosen here rather than mid-quote.
// Each entry deep-links the wizard onto that service path (`?service=`).
const SERVICE_ENTRIES: {
  service: ServiceKey;
  label: string;
  blurb: string;
  Icon: LucideIcon;
  /** Whether this workspace sells the service, mirroring the wizard's picker. */
  offered: (pricing: PricingSettings | undefined) => boolean;
}[] = [
  {
    service: "landscape",
    label: "Landscape Lighting",
    blurb: "Architectural fixtures & bistro",
    Icon: Trees,
    // Landscape is always on the menu, matching the wizard's picker.
    offered: () => true,
  },
  {
    service: "permanent",
    label: "Holiday Lights — Permanent",
    blurb: "Year-round LED roofline track",
    Icon: Cable,
    offered: (pricing) => Boolean(pricing?.permanent?.enabled),
  },
  {
    service: "christmas",
    label: "Christmas & Holiday Lighting",
    blurb: "Seasonal roofline, trees & wreaths",
    Icon: Snowflake,
    offered: (pricing) => Boolean(pricing?.christmas?.enabled),
  },
];

function LightDesignerTab() {
  const { currentWorkspaceId, isPending } = useWorkspace();
  return (
    <div className="h-full overflow-y-auto">
      {isPending || !currentWorkspaceId ? (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          Loading workspace…
        </div>
      ) : (
        <LightDesigner workspaceId={currentWorkspaceId} />
      )}
    </div>
  );
}

function QuotesHub() {
  const { currentWorkspaceId } = useWorkspace();
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const defaultTab =
    requestedTab && TAB_VALUES.has(requestedTab) ? requestedTab : "quotes";

  // Only offer services this workspace actually sells, so a menu entry can never
  // land the rep on a branch with nothing to price.
  const { data: pricing } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(currentWorkspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(currentWorkspaceId!),
    enabled: !!currentWorkspaceId,
    staleTime: 5 * 60_000,
  });
  const services = SERVICE_ENTRIES.filter((entry) => entry.offered(pricing));

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-col gap-4 p-6 pb-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Quotes &amp; Estimates
          </h1>
          <p className="text-sm text-muted-foreground">
            Build a quote, design the lights on a photo of the home, then send,
            approve, and convert wins into jobs and invoices — all in one place.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {services.length === 1 ? (
            // Nothing to pick when the workspace sells one service, so the hub
            // keeps its original one-click entry point onto that branch.
            <Button asChild size="sm">
              <Link href={`/sales-wizard?service=${services[0].service}`}>
                <Calculator className="h-4 w-4" />
                Build a quote
              </Link>
            </Button>
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm">
                  <Calculator className="h-4 w-4" />
                  Build a quote
                  <ChevronDown className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuLabel>Pick a service</DropdownMenuLabel>
                {services.map((entry) => (
                  <DropdownMenuItem key={entry.service} asChild>
                    <Link href={`/sales-wizard?service=${entry.service}`}>
                      <entry.Icon className="size-4" />
                      <span className="flex flex-col gap-0.5">
                        <span>{entry.label}</span>
                        <span className="text-xs text-muted-foreground">
                          {entry.blurb}
                        </span>
                      </span>
                    </Link>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      <Tabs
        defaultValue={defaultTab}
        className="flex min-h-0 flex-1 flex-col gap-0"
      >
        <div className="overflow-x-auto px-6">
          <TabsList>
            <TabsTrigger value="quotes" className="gap-2">
              <FileText className="size-4" />
              Quotes
            </TabsTrigger>
            <TabsTrigger value="designer" className="gap-2">
              <Ruler className="size-4" />
              Light Designer
            </TabsTrigger>
            <TabsTrigger value="copy-to-job" className="gap-2">
              <ClipboardCopy className="size-4" />
              Copy to Job
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent
          value="quotes"
          className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-4"
        >
          <QuotesList />
        </TabsContent>

        <TabsContent
          value="designer"
          className="min-h-0 flex-1 overflow-hidden pt-4"
        >
          <LightDesignerTab />
        </TabsContent>

        <TabsContent value="copy-to-job" className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-4">
          <CopyToJobTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function QuotesRoute() {
  return (
    <AppSidebar>
      {/* Suspense: QuotesHub reads useSearchParams (?tab=...). */}
      <Suspense fallback={<PageLoadingState />}>
        <QuotesHub />
      </Suspense>
    </AppSidebar>
  );
}
