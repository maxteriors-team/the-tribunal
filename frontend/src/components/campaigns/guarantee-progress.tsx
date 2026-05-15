"use client";

import { useQuery } from "@tanstack/react-query";
import { Shield, ShieldCheck, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { campaignsApi } from "@/lib/api/campaigns";
import { formatDate } from "@/lib/utils/date";
import { voiceCampaignsApi } from "@/lib/api/voice-campaigns";
import type { GuaranteeProgress as GuaranteeProgressType } from "@/types";

interface GuaranteeProgressProps {
  campaignId: string;
  campaignType: string;
}

export function GuaranteeProgress({ campaignId, campaignType }: GuaranteeProgressProps) {
  const workspaceId = useWorkspaceId();

  const { data: progress, isPending } = useQuery<GuaranteeProgressType>({
    queryKey: queryKeys.campaigns.guaranteeProgress(workspaceId ?? "", campaignId),
    queryFn: async () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      if (campaignType === "voice_sms_fallback") {
        return voiceCampaignsApi.getGuaranteeProgress(workspaceId, campaignId);
      }
      return campaignsApi.getGuaranteeProgress(workspaceId, campaignId);
    },
    enabled: !!workspaceId,
    refetchInterval: 30000,
  });

  if (isPending || !progress) {
    return null;
  }

  const target = progress.guarantee_target ?? 0;
  const completed = progress.appointments_completed;
  const booked = progress.appointments_booked;
  const percentage = target > 0 ? Math.min(100, Math.round((completed / target) * 100)) : 0;

  const statusConfig = {
    pending: {
      label: "In Progress",
      variant: "secondary" as const,
      icon: Shield,
      color: "text-info",
    },
    met: {
      label: "Guarantee Met",
      variant: "default" as const,
      icon: ShieldCheck,
      color: "text-success",
    },
    missed: {
      label: "Guarantee Missed",
      variant: "destructive" as const,
      icon: ShieldAlert,
      color: "text-destructive",
    },
  };

  const status = progress.guarantee_status && progress.guarantee_status in statusConfig
    ? statusConfig[progress.guarantee_status as keyof typeof statusConfig]
    : statusConfig.pending;

  const StatusIcon = status.icon;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <StatusIcon className={`size-5 ${status.color}`} />
            Guarantee Progress
          </CardTitle>
          <Badge variant={status.variant}>{status.label}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Progress bar */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {completed} / {target} completed
            </span>
            <span className="font-medium">{percentage}%</span>
          </div>
          <Progress value={percentage} className="h-3" />
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-2xl font-bold">{booked}</p>
            <p className="text-xs text-muted-foreground">Booked</p>
          </div>
          <div>
            <p className="text-2xl font-bold">{completed}</p>
            <p className="text-xs text-muted-foreground">Completed</p>
          </div>
          <div>
            <p className="text-2xl font-bold">{target}</p>
            <p className="text-xs text-muted-foreground">Target</p>
          </div>
        </div>

        {/* Days remaining */}
        {progress.days_remaining !== null && progress.guarantee_status === "pending" && (
          <div className="flex items-center justify-between pt-2 border-t">
            <span className="text-sm text-muted-foreground">Days Remaining</span>
            <span className="text-lg font-bold">{progress.days_remaining}</span>
          </div>
        )}

        {progress.deadline && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Deadline</span>
            <span>{formatDate(progress.deadline)}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
