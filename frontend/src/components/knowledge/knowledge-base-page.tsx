"use client";

import { BookOpen } from "lucide-react";
import { useState } from "react";

import { KnowledgeBaseTab } from "@/components/agents/tabs";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAgents } from "@/hooks/useAgents";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";

export function KnowledgeBasePage() {
  const workspaceId = useWorkspaceId();
  const { data, isPending, error, refetch } = useAgents(workspaceId ?? "");
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const agents = data?.items ?? [];
  const activeAgentId = selectedAgentId ?? agents[0]?.id ?? null;

  return (
    <AppSidebar>
      <div className="space-y-6 p-4 sm:p-6">
        <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
              <BookOpen className="size-6" />
              Knowledge Base
            </h1>
            <p className="text-muted-foreground">
              Manage the documents your AI agents use to answer questions on-brand.
            </p>
          </div>
          {agents.length > 0 && activeAgentId && (
            <Select value={activeAgentId} onValueChange={setSelectedAgentId}>
              <SelectTrigger aria-label="Select an agent" className="w-full sm:w-56">
                <SelectValue placeholder="Select an agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {!workspaceId || isPending ? (
          <PageLoadingState message="Loading agents…" />
        ) : error ? (
          <PageErrorState message="Failed to load agents." onRetry={() => refetch()} />
        ) : agents.length === 0 || !activeAgentId ? (
          <PageEmptyState
            icon={<BookOpen className="size-8" />}
            title="No agents yet"
            description="Create an AI agent first, then add knowledge documents it can draw from."
          />
        ) : (
          <KnowledgeBaseTab agentId={activeAgentId} />
        )}
      </div>
    </AppSidebar>
  );
}
