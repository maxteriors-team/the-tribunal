"use client";

import { Gauge } from "lucide-react";
import { useState } from "react";

import { PageEmptyState } from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";

import { AtRiskDealsList } from "./at-risk-deals-list";
import { DealCoachCard } from "./deal-coach-card";

export function DealCoachPage() {
  const workspaceId = useWorkspaceId();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="h-full overflow-y-auto">
      <div className="space-y-6 p-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Deal Coach</h1>
          <p className="text-sm text-muted-foreground">
            AI-ranked at-risk deals with the single next-best action for each
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
          {workspaceId ? (
            <AtRiskDealsList
              workspaceId={workspaceId}
              onSelect={setSelectedId}
            />
          ) : null}

          <div>
            {workspaceId && selectedId ? (
              <DealCoachCard
                workspaceId={workspaceId}
                opportunityId={selectedId}
              />
            ) : (
              <PageEmptyState
                icon={<Gauge className="h-10 w-10" />}
                title="Select a deal"
                description="Pick a deal from the list to see its coaching card and drafted next-best action."
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
