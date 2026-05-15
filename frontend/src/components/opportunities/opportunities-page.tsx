"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { Plus, ListIcon, LayoutGrid } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OpportunitiesList } from "@/components/opportunities/opportunities-list";

const OpportunitiesBoard = dynamic(
  () => import("@/components/opportunities/opportunities-board").then((m) => m.OpportunitiesBoard),
  { ssr: false, loading: () => <div className="h-full w-full animate-pulse bg-muted/20" /> },
);
import { CreateOpportunityDialog } from "@/components/opportunities/create-opportunity-dialog";
import { CreatePipelineDialog } from "@/components/opportunities/create-pipeline-dialog";

interface OpportunitiesPageProps {
  workspaceId: string;
}

export function OpportunitiesPage({ workspaceId }: OpportunitiesPageProps) {
  const [createOpportunityOpen, setCreateOpportunityOpen] = React.useState(false);
  const [createPipelineOpen, setCreatePipelineOpen] = React.useState(false);

  return (
    <div className="h-full w-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b p-4 sm:p-6">
        <div className="flex-1">
          <h1 className="text-2xl font-bold">Opportunities</h1>
          <p className="text-sm text-muted-foreground">
            Manage your sales pipeline and track deals
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setCreatePipelineOpen(true)} size="sm" variant="outline">
            <Plus className="h-4 w-4 mr-1" />
            New Pipeline
          </Button>
          <Button onClick={() => setCreateOpportunityOpen(true)} size="sm">
            <Plus className="h-4 w-4 mr-1" />
            New Opportunity
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex-1 overflow-hidden">
        <Tabs defaultValue="board" className="h-full w-full flex flex-col">
          <TabsList className="border-b rounded-none w-full justify-start px-6">
            <TabsTrigger value="board" className="flex items-center gap-2">
              <LayoutGrid className="h-4 w-4" />
              Pipeline Board
            </TabsTrigger>
            <TabsTrigger value="list" className="flex items-center gap-2">
              <ListIcon className="h-4 w-4" />
              List View
            </TabsTrigger>
          </TabsList>

          <TabsContent value="board" className="flex-1 overflow-hidden">
            <OpportunitiesBoard workspaceId={workspaceId} />
          </TabsContent>

          <TabsContent value="list" className="flex-1 overflow-hidden">
            <OpportunitiesList workspaceId={workspaceId} />
          </TabsContent>
        </Tabs>
      </div>

      {/* Create pipeline dialog */}
      <CreatePipelineDialog
        open={createPipelineOpen}
        onOpenChange={setCreatePipelineOpen}
        workspaceId={workspaceId}
      />

      {/* Create opportunity dialog */}
      <CreateOpportunityDialog
        open={createOpportunityOpen}
        onOpenChange={setCreateOpportunityOpen}
        workspaceId={workspaceId}
      />
    </div>
  );
}
