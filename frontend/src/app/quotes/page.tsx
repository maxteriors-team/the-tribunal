"use client";

import { ClipboardCopy, FileText, Ruler } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { LightDesigner } from "@/components/estimator/light-designer";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { CopyToJobTab } from "@/components/quotes/copy-to-job-tab";
import { QuotesList } from "@/components/quotes/quotes-list";
import { PageLoadingState } from "@/components/ui/page-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { resolveWorkspaceBrand } from "@/lib/brand";
import { useWorkspace } from "@/providers/workspace-provider";

// Deep-linkable tabs so redirects and job links can land on a specific workflow.
const TAB_VALUES = new Set(["quotes", "designer", "copy-to-job"]);

function LightDesignerTab() {
  const { currentWorkspace, currentWorkspaceId, isPending } = useWorkspace();
  const workspaceBrand = resolveWorkspaceBrand(currentWorkspace?.workspace);
  return (
    <div className="h-full overflow-y-auto">
      {isPending || !currentWorkspaceId ? (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          Loading workspace…
        </div>
      ) : (
        <LightDesigner
          workspaceId={currentWorkspaceId}
          workspaceName={workspaceBrand.businessName}
          workspaceLogoUrl={workspaceBrand.logoUrl}
        />
      )}
    </div>
  );
}

function QuotesHub() {
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const defaultTab = requestedTab && TAB_VALUES.has(requestedTab) ? requestedTab : "quotes";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="p-6 pb-3">
        <h1 className="text-2xl font-semibold tracking-tight">Quotes &amp; Estimates</h1>
        <p className="text-sm text-muted-foreground">
          Design lights on a photo, then send, approve, and copy estimates into scheduled jobs.
        </p>
      </div>

      <Tabs defaultValue={defaultTab} className="flex min-h-0 flex-1 flex-col gap-0">
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

        <TabsContent value="quotes" className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-4">
          <QuotesList />
        </TabsContent>

        <TabsContent value="designer" className="min-h-0 flex-1 overflow-hidden pt-4">
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
