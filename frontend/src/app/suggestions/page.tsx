"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Wand2, Lightbulb, Check, X, Clock, BarChart3, FlaskConical } from "lucide-react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { improvementSuggestionsApi } from "@/lib/api/improvement-suggestions";
import { campaignReportsApi } from "@/lib/api/campaign-reports";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SuggestionsQueue } from "@/components/suggestions/suggestions-queue";
import { CampaignReportsList } from "@/components/suggestions/campaign-reports-list";
import { ExperimentDashboard } from "@/components/suggestions/experiment-dashboard";

export default function SuggestionsPage() {
  const workspaceId = useWorkspaceId();
  const [activeTab, setActiveTab] = useState("prompts");
  const [statusFilter, setStatusFilter] = useState("pending");

  const { data: pendingCount } = useQuery({
    queryKey: queryKeys.improvementSuggestions.pendingCount(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return improvementSuggestionsApi.getPendingCount(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const { data: reportCount } = useQuery({
    queryKey: queryKeys.campaignReports.count(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return campaignReportsApi.getCount(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const { data: suggestionStats, isPending: statsLoading } = useQuery({
    queryKey: queryKeys.improvementSuggestions.stats(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return improvementSuggestionsApi.getStats(workspaceId);
    },
    enabled: !!workspaceId,
  });

  return (
    <AppSidebar>
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI Suggestions</h1>
          <p className="text-sm text-muted-foreground">
            Review AI-generated prompt improvements and campaign intelligence
          </p>
        </div>
        {pendingCount && pendingCount.pending_count > 0 && (
          <div className="flex items-center gap-2 rounded-lg border bg-warning/10 px-4 py-2">
            <Lightbulb className="h-5 w-5 text-warning" />
            <span className="text-sm font-medium">
              {pendingCount.pending_count} pending suggestion
              {pendingCount.pending_count !== 1 && "s"}
            </span>
          </div>
        )}
      </div>

      {/* Top-level tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="prompts" className="gap-2">
            <Wand2 className="h-4 w-4" />
            Prompt Suggestions
            {pendingCount && pendingCount.pending_count > 0 && (
              <span className="ml-1 rounded-full bg-warning px-1.5 py-0.5 text-xs text-white">
                {pendingCount.pending_count}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="intelligence" className="gap-2">
            <BarChart3 className="h-4 w-4" />
            Campaign Intelligence
            {reportCount && reportCount.report_count > 0 && (
              <span className="ml-1 rounded-full bg-info px-1.5 py-0.5 text-xs text-white">
                {reportCount.report_count}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="experiments" className="gap-2">
            <FlaskConical className="h-4 w-4" />
            Experiments
          </TabsTrigger>
        </TabsList>

        {/* Prompt Suggestions tab */}
        <TabsContent value="prompts" className="mt-6 space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">Pending</CardTitle>
                <Clock className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{pendingCount?.pending_count ?? 0}</div>
                <p className="text-xs text-muted-foreground">Awaiting review</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">Approved</CardTitle>
                <Check className="h-4 w-4 text-success" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {statsLoading ? "-" : (suggestionStats?.approved_count ?? 0)}
                </div>
                <p className="text-xs text-muted-foreground">All time</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">Rejected</CardTitle>
                <X className="h-4 w-4 text-destructive" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {statsLoading ? "-" : (suggestionStats?.rejected_count ?? 0)}
                </div>
                <p className="text-xs text-muted-foreground">All time</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">Auto-Generated</CardTitle>
                <Wand2 className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {statsLoading ? "-" : (suggestionStats?.auto_generated_count ?? 0)}
                </div>
                <p className="text-xs text-muted-foreground">This month</p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Suggestion Queue</CardTitle>
              <CardDescription>
                AI-generated prompt improvements based on call performance analysis
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Tabs value={statusFilter} onValueChange={setStatusFilter}>
                <TabsList>
                  <TabsTrigger value="pending">
                    Pending
                    {pendingCount && pendingCount.pending_count > 0 && (
                      <span className="ml-1.5 rounded-full bg-warning px-1.5 py-0.5 text-xs text-white">
                        {pendingCount.pending_count}
                      </span>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="approved">Approved</TabsTrigger>
                  <TabsTrigger value="rejected">Rejected</TabsTrigger>
                </TabsList>

                <TabsContent value="pending" className="mt-4">
                  <SuggestionsQueue statusFilter="pending" />
                </TabsContent>
                <TabsContent value="approved" className="mt-4">
                  <SuggestionsQueue statusFilter="approved" />
                </TabsContent>
                <TabsContent value="rejected" className="mt-4">
                  <SuggestionsQueue statusFilter="rejected" />
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Campaign Intelligence tab */}
        <TabsContent value="intelligence" className="mt-6">
          <CampaignReportsList />
        </TabsContent>

        {/* Experiments tab */}
        <TabsContent value="experiments" className="mt-6">
          <ExperimentDashboard />
        </TabsContent>
      </Tabs>
    </div>
    </AppSidebar>
  );
}
