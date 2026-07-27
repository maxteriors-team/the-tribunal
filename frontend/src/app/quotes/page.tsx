"use client";

import { Calculator, FileText, Ruler } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { RooflineEstimator } from "@/components/estimator/roofline-estimator";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { QuotesList } from "@/components/quotes/quotes-list";
import { Button } from "@/components/ui/button";
import { PageLoadingState } from "@/components/ui/page-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useWorkspace } from "@/providers/workspace-provider";

// Deep-linkable tabs so the command palette / `/estimator` redirect can land the
// rep straight on the Photo Designer (`?tab=designer`).
const TAB_VALUES = new Set(["quotes", "designer"]);

function PhotoDesignerTab() {
  const { currentWorkspaceId, isPending } = useWorkspace();
  return (
    <div className="h-full overflow-y-auto">
      {isPending || !currentWorkspaceId ? (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          Loading workspace…
        </div>
      ) : (
        <RooflineEstimator workspaceId={currentWorkspaceId} />
      )}
    </div>
  );
}

function QuotesHub() {
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const defaultTab =
    requestedTab && TAB_VALUES.has(requestedTab) ? requestedTab : "quotes";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-col gap-4 p-6 pb-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Quotes &amp; Estimates
          </h1>
          <p className="text-sm text-muted-foreground">
            Build a quote, design lights on a photo, then send, approve, and
            convert wins into jobs and invoices — all in one place.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button asChild size="sm">
            <Link href="/sales-wizard">
              <Calculator className="h-4 w-4" />
              Build a quote
            </Link>
          </Button>
        </div>
      </div>

      <Tabs
        defaultValue={defaultTab}
        className="flex min-h-0 flex-1 flex-col gap-0"
      >
        <div className="px-6">
          <TabsList>
            <TabsTrigger value="quotes" className="gap-2">
              <FileText className="size-4" />
              Quotes
            </TabsTrigger>
            <TabsTrigger value="designer" className="gap-2">
              <Ruler className="size-4" />
              Photo Designer
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
          <PhotoDesignerTab />
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
