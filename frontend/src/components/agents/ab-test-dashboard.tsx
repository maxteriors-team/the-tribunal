"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Trophy,
  TrendingUp,
  AlertCircle,
  Loader2,
  Play,
  Pause,
  X,
  FlaskConical,
} from "lucide-react";

import {
  promptVersionsApi,
  type VersionComparisonItem,
} from "@/lib/api/prompt-versions";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { POLL_30S } from "@/lib/query-options";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
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
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";
import { useState } from "react";

interface ABTestDashboardProps {
  agentId: string;
}

export function ABTestDashboard({ agentId }: ABTestDashboardProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [declareWinnerVersion, setDeclareWinnerVersion] = useState<string | null>(null);
  const [eliminateVersion, setEliminateVersion] = useState<string | null>(null);

  const { data: comparison, isPending } = useQuery({
    queryKey: queryKeys.agents.promptVersionComparison(workspaceId ?? "", agentId),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.compare(workspaceId, agentId);
    },
    enabled: !!workspaceId,
    ...POLL_30S,
  });

  const activateMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.activate(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Winner declared! Other versions deactivated.");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionComparisonAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to resume version")),
  });

  const eliminateMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.eliminate(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version eliminated from testing");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionComparisonAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
      setEliminateVersion(null);
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to eliminate version")),
  });

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!comparison?.versions.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <FlaskConical className="mb-4 h-12 w-12 text-muted-foreground" />
          <h3 className="mb-2 text-lg font-semibold">No A/B Test Running</h3>
          <p className="mb-4 max-w-sm text-sm text-muted-foreground">
            Activate multiple prompt versions to start an A/B test. The system will
            automatically split traffic using Thompson Sampling.
          </p>
        </CardContent>
      </Card>
    );
  }

  const getRecommendationCard = () => {
    const { recommended_action, winner_id, winner_probability, min_samples_needed } = comparison;

    if (recommended_action === "declare_winner" && winner_id && winner_probability) {
      const winnerVersion = comparison.versions.find((v) => v.version_id === winner_id);
      return (
        <Card className="border-success bg-success/10">
          <CardContent className="flex items-center justify-between p-4">
            <div className="flex items-center gap-3">
              <Trophy className="h-6 w-6 text-success" />
              <div>
                <p className="font-medium">Winner Detected!</p>
                <p className="text-sm text-muted-foreground">
                  Version {winnerVersion?.version_number} has a{" "}
                  {(winner_probability * 100).toFixed(1)}% chance of being best
                </p>
              </div>
            </div>
            <Button
              onClick={() => setDeclareWinnerVersion(winner_id)}
              className="bg-success hover:bg-success/90"
            >
              Declare Winner
            </Button>
          </CardContent>
        </Card>
      );
    }

    if (recommended_action === "eliminate_worst") {
      const worstVersion = comparison.versions[comparison.versions.length - 1];
      return (
        <Card className="border-warning bg-warning/10">
          <CardContent className="flex items-center justify-between p-4">
            <div className="flex items-center gap-3">
              <AlertCircle className="h-6 w-6 text-warning" />
              <div>
                <p className="font-medium">Consider Eliminating Underperformer</p>
                <p className="text-sm text-muted-foreground">
                  Version {worstVersion?.version_number} is performing significantly worse
                </p>
              </div>
            </div>
            <Button
              variant="outline"
              onClick={() => setEliminateVersion(worstVersion.version_id)}
              className="border-warning text-warning hover:bg-warning/10"
            >
              Eliminate
            </Button>
          </CardContent>
        </Card>
      );
    }

    if (min_samples_needed > 0) {
      return (
        <Card className="border-info bg-info/10">
          <CardContent className="flex items-center gap-3 p-4">
            <TrendingUp className="h-6 w-6 text-info" />
            <div>
              <p className="font-medium">Collecting Data</p>
              <p className="text-sm text-muted-foreground">
                Need {min_samples_needed} more samples for reliable statistical analysis
              </p>
            </div>
          </CardContent>
        </Card>
      );
    }

    return (
      <Card className="border-muted">
        <CardContent className="flex items-center gap-3 p-4">
          <FlaskConical className="h-6 w-6 text-muted-foreground" />
          <div>
            <p className="font-medium">Test In Progress</p>
            <p className="text-sm text-muted-foreground">
              Continue testing to reach statistical significance
            </p>
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-6">
      {getRecommendationCard()}

      <div className="grid gap-4 md:grid-cols-2">
        {comparison.versions.map((version) => (
          <VersionCard
            key={version.version_id}
            version={version}
            isWinner={comparison.winner_id === version.version_id}
            onPause={() => pauseMutation.mutate(version.version_id)}
            onResume={() => resumeMutation.mutate(version.version_id)}
            onEliminate={() => setEliminateVersion(version.version_id)}
            onDeclareWinner={() => setDeclareWinnerVersion(version.version_id)}
          />
        ))}
      </div>

      <AlertDialog
        open={!!declareWinnerVersion}
        onOpenChange={() => setDeclareWinnerVersion(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Declare Winner?</AlertDialogTitle>
            <AlertDialogDescription>
              This will deactivate all other versions and make this the only active
              version. The A/B test will end.
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

      <AlertDialog
        open={!!eliminateVersion}
        onOpenChange={() => setEliminateVersion(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminate Version?</AlertDialogTitle>
            <AlertDialogDescription>
              This version will be permanently removed from A/B testing. This action
              cannot be undone.
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
    </div>
  );
}

interface VersionCardProps {
  version: VersionComparisonItem;
  isWinner: boolean;
  onPause: () => void;
  onResume: () => void;
  onEliminate: () => void;
  onDeclareWinner: () => void;
}

function VersionCard({
  version,
  isWinner,
  onPause,
  onResume,
  onEliminate,
  onDeclareWinner,
}: VersionCardProps) {
  const probabilityPercent = version.probability_best * 100;
  const isPaused = version.arm_status === "paused";

  return (
    <Card
      className={cn(
        isWinner && "border-success ring-1 ring-success",
        isPaused && "opacity-60"
      )}
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-lg">Version {version.version_number}</CardTitle>
            {version.is_baseline && (
              <Badge variant="outline" className="text-xs">
                Baseline
              </Badge>
            )}
            {isWinner && (
              <Badge className="bg-success text-xs">
                <Trophy className="mr-1 h-3 w-3" />
                Leader
              </Badge>
            )}
            {isPaused && (
              <Badge variant="secondary" className="text-xs">
                <Pause className="mr-1 h-3 w-3" />
                Paused
              </Badge>
            )}
          </div>
          <div className="flex gap-1">
            {isPaused ? (
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onResume} aria-label="Resume variant">
                <Play className="h-4 w-4" />
              </Button>
            ) : (
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onPause} aria-label="Pause variant">
                <Pause className="h-4 w-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-destructive"
              onClick={onEliminate}
              aria-label="Eliminate variant"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <CardDescription>
          {formatNumber(version.sample_size)} samples collected
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Probability of Being Best</span>
            <span className="font-medium">{probabilityPercent.toFixed(1)}%</span>
          </div>
          <Progress
            value={probabilityPercent}
            className={cn(
              "h-3",
              probabilityPercent > 80 && "[&>div]:bg-success",
              probabilityPercent < 20 && "[&>div]:bg-destructive"
            )}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-muted-foreground">Booking Rate</p>
            <p className="text-lg font-semibold">
              {version.booking_rate !== null
                ? `${(version.booking_rate * 100).toFixed(1)}%`
                : "-"}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Mean Estimate</p>
            <p className="text-lg font-semibold">
              {(version.mean_estimate * 100).toFixed(1)}%
            </p>
          </div>
        </div>

        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-xs text-muted-foreground">95% Credible Interval</p>
          <p className="text-sm font-medium">
            {(version.credible_interval_lower * 100).toFixed(1)}% -{" "}
            {(version.credible_interval_upper * 100).toFixed(1)}%
          </p>
        </div>

        {probabilityPercent > 90 && (
          <Button className="w-full" variant="outline" onClick={onDeclareWinner}>
            <Trophy className="mr-2 h-4 w-4" />
            Declare Winner
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
