"use client";

import { memo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Bell,
  Bot,
  CheckCircle,
  Clock,
  Megaphone,
  MessageSquare,
  Phone,
  Users,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { nudgesApi } from "@/lib/api/nudges";
import { queryKeys } from "@/lib/query-keys";
import type { TodayOverview } from "@/lib/api/dashboard";

interface TodayOverviewCardProps {
  overview: TodayOverview | undefined;
  isPending: boolean;
}

export const TodayOverviewCard = memo(function TodayOverviewCard({
  overview,
  isPending,
}: TodayOverviewCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="gradient-heading">Today&apos;s Overview</CardTitle>
        <CardDescription className="flex items-center gap-1.5">
          <Phone className="size-3" />
          <MessageSquare className="size-3" />
          Outbound call &amp; SMS delivery status
        </CardDescription>
      </CardHeader>
      <CardContent>
        <TooltipProvider>
          <div className="grid grid-cols-3 gap-4 text-center">
            {isPending ? (
              <>
                {[1, 2, 3].map((i) => (
                  <div key={i} className="space-y-1">
                    <Skeleton className="h-8 w-12 mx-auto" />
                    <Skeleton className="h-3 w-16 mx-auto" />
                  </div>
                ))}
              </>
            ) : (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="space-y-1 cursor-default">
                      <div className="flex items-center justify-center gap-1 text-success">
                        <CheckCircle className="size-4" />
                        <span className="text-2xl font-bold">
                          {overview?.completed ?? 0}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">Completed</p>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Calls answered &amp; SMS delivered or sent today</p>
                  </TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="space-y-1 cursor-default">
                      <div className="flex items-center justify-center gap-1 text-warning">
                        <Clock className="size-4" />
                        <span className="text-2xl font-bold">
                          {overview?.pending ?? 0}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">Pending</p>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Calls &amp; messages currently queued or in progress</p>
                  </TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="space-y-1 cursor-default">
                      <div className="flex items-center justify-center gap-1 text-destructive">
                        <XCircle className="size-4" />
                        <span className="text-2xl font-bold">
                          {overview?.failed ?? 0}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">Failed</p>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Calls &amp; messages that could not be delivered today</p>
                  </TooltipContent>
                </Tooltip>
              </>
            )}
          </div>
        </TooltipProvider>
      </CardContent>
    </Card>
  );
});

export const QuickActionsCard = memo(function QuickActionsCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="gradient-heading">Quick Actions</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2">
        <Button variant="outline" className="justify-start" asChild>
          <Link href="/campaigns/new">
            <Megaphone className="mr-2 size-4" />
            New Campaign
          </Link>
        </Button>
        <Button variant="outline" className="justify-start" asChild>
          <Link href="/?import=true">
            <Users className="mr-2 size-4" />
            Import Contacts
          </Link>
        </Button>
        <Button variant="outline" className="justify-start" asChild>
          <Link href="/agents">
            <Bot className="mr-2 size-4" />
            Configure Agent
          </Link>
        </Button>
        <Button variant="outline" className="justify-start" asChild>
          <Link href="/calls">
            <Phone className="mr-2 size-4" />
            View Call Logs
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
});

interface NudgesCardProps {
  workspaceId: string | null;
}

export const NudgesCard = memo(function NudgesCard({ workspaceId }: NudgesCardProps) {
  const { data: nudgeStats, isPending } = useQuery({
    queryKey: queryKeys.nudges.stats(workspaceId ?? ""),
    queryFn: () => nudgesApi.getStats(workspaceId!),
    enabled: !!workspaceId,
    refetchInterval: 60000,
  });

  const pending = nudgeStats?.pending ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 gradient-heading">
          <Bell className="size-5" />
          Nudges
        </CardTitle>
        <CardDescription>Relationship reminders</CardDescription>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <Skeleton className="h-8 w-32" />
        ) : pending > 0 ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold text-orange-500">{pending}</span>
              <span className="text-sm text-muted-foreground">
                nudge{pending !== 1 ? "s" : ""} pending
              </span>
            </div>
            <Button variant="outline" size="sm" asChild>
              <Link href="/nudges">
                View Nudges
                <ArrowUpRight className="ml-2 size-4" />
              </Link>
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No pending nudges 🎉</p>
        )}
      </CardContent>
    </Card>
  );
});
