"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2 } from "lucide-react";

import {
  campaignReportsApi,
  type CampaignReportResponse,
} from "@/lib/api/campaign-reports";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Card, CardContent } from "@/components/ui/card";
import { CampaignReportCard } from "./campaign-report-card";

export function CampaignReportsList() {
  const workspaceId = useWorkspaceId();

  const { data, isPending } = useQuery({
    queryKey: queryKeys.campaignReports.list(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return campaignReportsApi.list(workspaceId, { page_size: 50 });
    },
    enabled: !!workspaceId,
  });

  // Fetch full reports for each summary item
  const reportIds = data?.items.map((item) => item.id) ?? [];
  const { data: fullReports } = useQuery({
    queryKey: queryKeys.campaignReports.full(workspaceId ?? "", reportIds),
    queryFn: async () => {
      if (!workspaceId || !data?.items.length) return [];
      const reports = await Promise.all(
        data.items.map((item) => campaignReportsApi.get(workspaceId, item.id))
      );
      return reports;
    },
    enabled: !!workspaceId && !!data?.items.length,
  });

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!data?.items.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <BarChart3 className="mb-4 h-12 w-12 text-muted-foreground" />
          <h3 className="mb-2 text-lg font-semibold">No Campaign Reports</h3>
          <p className="max-w-sm text-sm text-muted-foreground">
            When campaigns complete, AI will automatically analyze the results and
            generate intelligence reports here. You can also manually trigger a
            report from any completed campaign.
          </p>
        </CardContent>
      </Card>
    );
  }

  const reports: CampaignReportResponse[] = fullReports ?? data.items.map((item) => ({
    ...item,
    workspace_id: workspaceId ?? "",
    error_message: null,
    metrics_snapshot: null,
    key_findings: null,
    what_worked: null,
    what_didnt_work: null,
    recommendations: null,
    segment_analysis: null,
    timing_analysis: null,
    prompt_performance: null,
    generated_suggestion_ids: null,
  }));

  return (
    <div className="space-y-4">
      {reports.map((report) => (
        <CampaignReportCard key={report.id} report={report} />
      ))}
    </div>
  );
}
