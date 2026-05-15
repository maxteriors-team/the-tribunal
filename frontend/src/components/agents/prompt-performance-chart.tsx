"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, TrendingUp } from "lucide-react";

import {
  promptVersionsApi,
  type PromptVersionResponse,
} from "@/lib/api/prompt-versions";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { formatNumber } from "@/lib/utils/number";

interface PromptPerformanceChartProps {
  agentId: string;
}

export function PromptPerformanceChart({ agentId }: PromptPerformanceChartProps) {
  const workspaceId = useWorkspaceId();

  const { data: versions, isPending } = useQuery({
    queryKey: queryKeys.agents.promptVersions(workspaceId ?? "", agentId),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.list(workspaceId, agentId, { page_size: 20 });
    },
    enabled: !!workspaceId,
  });

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!versions?.items.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <TrendingUp className="mb-4 h-12 w-12 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No performance data available yet</p>
        </CardContent>
      </Card>
    );
  }

  // Sort by version number for display
  const sortedVersions = [...versions.items]
    .sort((a, b) => a.version_number - b.version_number)
    .filter((v) => v.total_calls > 0);

  if (sortedVersions.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <TrendingUp className="mb-4 h-12 w-12 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No calls have been made with tracked prompt versions yet
          </p>
        </CardContent>
      </Card>
    );
  }

  // Find max values for scaling
  const maxCalls = Math.max(...sortedVersions.map((v) => v.total_calls));

  const getBookingRate = (version: PromptVersionResponse) => {
    if (version.successful_calls === 0) return 0;
    return (version.booked_appointments / version.successful_calls) * 100;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Performance by Version</CardTitle>
        <CardDescription>
          Booking rate and call volume across prompt versions
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {sortedVersions.map((version) => {
            const bookingRate = getBookingRate(version);
            const callsPercent = (version.total_calls / maxCalls) * 100;

            return (
              <div key={version.id} className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-mono">v{version.version_number}</span>
                    {version.is_active && (
                      <span className="h-2 w-2 rounded-full bg-success" />
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-muted-foreground">
                    <span>{formatNumber(version.total_calls)} calls</span>
                    <span className="font-medium text-foreground">
                      {bookingRate.toFixed(1)}% booking rate
                    </span>
                  </div>
                </div>
                <div className="relative h-3 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="absolute left-0 h-full bg-primary/30 transition-all duration-500"
                    style={{ width: `${callsPercent}%` }}
                  />
                  <div
                    className="absolute left-0 h-full bg-primary transition-all duration-500"
                    style={{ width: `${bookingRate}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-6 flex items-center gap-6 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded bg-primary" />
            <span>Booking Rate</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded bg-primary/30" />
            <span>Call Volume (relative)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-success" />
            <span>Active</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
