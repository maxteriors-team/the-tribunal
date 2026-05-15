"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  Trophy,
  TrendingUp,
  AlertCircle,
  Play,
  Pause,
  X,
  FlaskConical,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";

import {
  promptVersionsApi,
  type VersionComparisonResponse,
} from "@/lib/api/prompt-versions";
import { useAgents } from "@/hooks/useAgents";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";

export function ExperimentDashboard() {
  const workspaceId = useWorkspaceId();
  const { data: agentsData, isPending: agentsLoading } = useAgents(workspaceId ?? "", { page_size: 100 });

  const agents = agentsData?.items ?? [];

  if (agentsLoading) {
    return (
      <div className="space-y-6">
        {[1, 2].map((i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-4 w-32" />
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 md:grid-cols-2">
                <Skeleton className="h-48" />
                <Skeleton className="h-48" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <FlaskConical className="mb-4 h-12 w-12 text-muted-foreground" />
          <h3 className="mb-2 text-lg font-semibold">No Agents Found</h3>
          <p className="mb-4 max-w-sm text-sm text-muted-foreground">
            Create agents and activate multiple prompt versions to start experiments.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {agents.map((agent) => (
        <AgentExperimentSection key={agent.id} agentId={agent.id} agentName={agent.name} />
      ))}
    </div>
  );
}

function AgentExperimentSection({ agentId, agentName }: { agentId: string; agentName: string }) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [declareWinnerVersion, setDeclareWinnerVersion] = useState<string | null>(null);
  const [eliminateVersion, setEliminateVersion] = useState<string | null>(null);

  const { data: comparison, isPending } = useQuery<VersionComparisonResponse>({
    queryKey: queryKeys.agents.promptVersionComparison(workspaceId ?? "", agentId),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.compare(workspaceId, agentId);
    },
    enabled: !!workspaceId,
    ...POLL_60S,
  });

  const activateMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.activate(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Winner declared!");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionComparisonAll() });
      setDeclareWinnerVersion(null);
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to declare winner")),
  });

  const pauseMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.pause(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version paused");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionComparisonAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to pause version")),
  });

  const resumeMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.resume(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version resumed");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionComparisonAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to resume version")),
  });

  const eliminateMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.eliminate(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version eliminated");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionComparisonAll() });
      setEliminateVersion(null);
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to eliminate version")),
  });

  if (isPending) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32" />
        </CardContent>
      </Card>
    );
  }

  // Don't render agents with no active experiment (0 or 1 versions)
  if (!comparison?.versions.length || comparison.versions.length < 2) {
    return null;
  }

  const { recommended_action, winner_id, winner_probability, min_samples_needed } = comparison;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <FlaskConical className="h-4 w-4" />
              {agentName}
              <Badge variant="outline" className="text-xs">
                {comparison.versions.length} versions
              </Badge>
            </CardTitle>
            <CardDescription>
              <Link href={`/agents/${agentId}`} className="inline-flex items-center gap-1 hover:underline">
                View agent details
                <ExternalLink className="h-3 w-3" />
              </Link>
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Recommendation Banner */}
        {recommended_action === "declare_winner" && winner_id && winner_probability ? (
          <div className="flex items-center justify-between rounded-lg border border-success/20 bg-success/10 p-3">
            <div className="flex items-center gap-3">
              <Trophy className="h-5 w-5 text-success" />
              <div>
                <p className="text-sm font-medium">Winner Detected</p>
                <p className="text-xs text-muted-foreground">
                  Version {comparison.versions.find(v => v.version_id === winner_id)?.version_number} — {(winner_probability * 100).toFixed(1)}% probability best
                </p>
              </div>
            </div>
            <Button size="sm" onClick={() => setDeclareWinnerVersion(winner_id)} className="bg-success hover:bg-success/90">
              Declare Winner
            </Button>
          </div>
        ) : recommended_action === "eliminate_worst" ? (
          <div className="flex items-center justify-between rounded-lg border border-warning/20 bg-warning/10 p-3">
            <div className="flex items-center gap-3">
              <AlertCircle className="h-5 w-5 text-warning" />
              <div>
                <p className="text-sm font-medium">Eliminate Underperformer</p>
                <p className="text-xs text-muted-foreground">
                  Version {comparison.versions[comparison.versions.length - 1]?.version_number} is performing significantly worse
                </p>
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={() => setEliminateVersion(comparison.versions[comparison.versions.length - 1].version_id)} className="border-warning/20 text-warning hover:bg-warning/10">
              Eliminate
            </Button>
          </div>
        ) : min_samples_needed > 0 ? (
          <div className="flex items-center gap-3 rounded-lg border border-info/20 bg-info/10 p-3">
            <TrendingUp className="h-5 w-5 text-info" />
            <div>
              <p className="text-sm font-medium">Collecting Data</p>
              <p className="text-xs text-muted-foreground">
                Need {min_samples_needed} more samples for reliable analysis
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-lg border p-3">
            <FlaskConical className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">Test In Progress</p>
              <p className="text-xs text-muted-foreground">
                Continue testing to reach statistical significance
              </p>
            </div>
          </div>
        )}

        {/* Version Cards */}
        <div className="grid gap-4 md:grid-cols-2">
          {comparison.versions.map((version) => {
            const probabilityPercent = version.probability_best * 100;
            const isPaused = version.arm_status === "paused";
            const isWinner = comparison.winner_id === version.version_id;

            return (
              <div
                key={version.version_id}
                className={cn(
                  "rounded-lg border p-4 space-y-3",
                  isWinner && "border-success ring-1 ring-success",
                  isPaused && "opacity-60"
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">v{version.version_number}</span>
                    {version.is_baseline && (
                      <Badge variant="outline" className="text-[10px]">Baseline</Badge>
                    )}
                    {isPaused && (
                      <Badge variant="secondary" className="text-[10px]">Paused</Badge>
                    )}
                    {isWinner && (
                      <Badge className="bg-success text-[10px]">
                        <Trophy className="mr-0.5 h-2.5 w-2.5" />
                        Leader
                      </Badge>
                    )}
                  </div>
                  <div className="flex gap-1">
                    {isPaused ? (
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => resumeMutation.mutate(version.version_id)} aria-label="Resume variant">
                        <Play className="h-3.5 w-3.5" />
                      </Button>
                    ) : (
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => pauseMutation.mutate(version.version_id)} aria-label="Pause variant">
                        <Pause className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setEliminateVersion(version.version_id)} aria-label="Eliminate variant">
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>

                <div>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Probability Best</span>
                    <span className="font-medium">{probabilityPercent.toFixed(1)}%</span>
                  </div>
                  <Progress
                    value={probabilityPercent}
                    className={cn(
                      "h-2",
                      probabilityPercent > 80 && "[&>div]:bg-success",
                      probabilityPercent < 20 && "[&>div]:bg-destructive"
                    )}
                  />
                </div>

                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div>
                    <p className="text-muted-foreground">Samples</p>
                    <p className="font-medium">{formatNumber(version.sample_size)}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Booking Rate</p>
                    <p className="font-medium">
                      {version.booking_rate !== null ? `${(version.booking_rate * 100).toFixed(1)}%` : "-"}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">CI Range</p>
                    <p className="font-medium">
                      {(version.credible_interval_lower * 100).toFixed(1)}%-{(version.credible_interval_upper * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Dialogs */}
        <AlertDialog open={!!declareWinnerVersion} onOpenChange={() => setDeclareWinnerVersion(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Declare Winner?</AlertDialogTitle>
              <AlertDialogDescription>
                This will deactivate all other versions and make this the only active version. The A/B test will end.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => declareWinnerVersion && activateMutation.mutate(declareWinnerVersion)}
                disabled={activateMutation.isPending}
              >
                {activateMutation.isPending ? "Declaring..." : "Declare Winner"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <AlertDialog open={!!eliminateVersion} onOpenChange={() => setEliminateVersion(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Eliminate Version?</AlertDialogTitle>
              <AlertDialogDescription>
                This version will be permanently removed from A/B testing. This action cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => eliminateVersion && eliminateMutation.mutate(eliminateVersion)}
                disabled={eliminateMutation.isPending}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {eliminateMutation.isPending ? "Eliminating..." : "Eliminate"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}
