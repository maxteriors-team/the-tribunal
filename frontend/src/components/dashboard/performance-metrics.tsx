import { memo } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Bot,
  Calendar,
  CalendarCheck,
  CalendarDays,
  TrendingUp,
  UserX,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type {
  AgentStat,
  AppointmentStats,
  CampaignStat,
} from "@/lib/api/dashboard";

interface AppointmentStatsCardProps {
  appointmentStats: AppointmentStats | undefined;
  isPending: boolean;
}

export const AppointmentStatsCard = memo(function AppointmentStatsCard({
  appointmentStats,
  isPending,
}: AppointmentStatsCardProps) {
  const showUpRate = appointmentStats?.show_up_rate_30d ?? null;

  const rateColor =
    showUpRate === null
      ? "text-muted-foreground"
      : showUpRate >= 70
        ? "text-success"
        : showUpRate >= 50
          ? "text-warning"
          : "text-destructive";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="flex items-center gap-2 gradient-heading">
            <CalendarDays className="size-5" />
            Appointments
          </CardTitle>
          <CardDescription>Scheduling performance</CardDescription>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/calendar">
            View Calendar
            <ArrowUpRight className="ml-2 size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {isPending ? (
            <>
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="space-y-1 text-center">
                  <Skeleton className="h-8 w-12 mx-auto" />
                  <Skeleton className="h-3 w-16 mx-auto" />
                  <Skeleton className="h-3 w-20 mx-auto" />
                </div>
              ))}
            </>
          ) : (
            <>
              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-info">
                  <Calendar className="size-4" />
                  <span className="text-2xl font-bold">
                    {appointmentStats?.appointments_today ?? 0}
                  </span>
                </div>
                <p className="text-xs font-medium">Today</p>
                <p className="text-xs text-muted-foreground">Scheduled</p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-primary">
                  <CalendarCheck className="size-4" />
                  <span className="text-2xl font-bold">
                    {appointmentStats?.appointments_this_week ?? 0}
                  </span>
                </div>
                <p className="text-xs font-medium">This Week</p>
                <p className="text-xs text-muted-foreground">Upcoming</p>
              </div>

              <div className="space-y-1 text-center">
                <div className={`flex items-center justify-center gap-1 ${rateColor}`}>
                  <TrendingUp className="size-4" />
                  <span className="text-2xl font-bold">
                    {showUpRate !== null ? `${showUpRate}%` : "—"}
                  </span>
                </div>
                <p className="text-xs font-medium">Show-Up Rate</p>
                <p className="text-xs text-muted-foreground">
                  {showUpRate !== null ? "Last 30 days" : "Not enough data"}
                </p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-destructive">
                  <UserX className="size-4" />
                  <span className="text-2xl font-bold">
                    {appointmentStats?.no_shows_30d ?? 0}
                  </span>
                </div>
                <p className="text-xs font-medium">No-Shows</p>
                <p className="text-xs text-muted-foreground">Last 30 days</p>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
});

interface ActiveCampaignsCardProps {
  campaigns: CampaignStat[];
  isPending: boolean;
}

export const ActiveCampaignsCard = memo(function ActiveCampaignsCard({
  campaigns,
  isPending,
}: ActiveCampaignsCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="gradient-heading">Active Campaigns</CardTitle>
          <CardDescription>
            Currently running and scheduled campaigns
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/campaigns">
            View All
            <ArrowUpRight className="ml-2 size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {isPending ? (
          <>
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-4 p-3 rounded-lg border">
                <div className="flex-1 space-y-2">
                  <div className="flex items-center justify-between">
                    <Skeleton className="h-5 w-40" />
                    <Skeleton className="h-4 w-16" />
                  </div>
                  <Skeleton className="h-2 w-full" />
                </div>
              </div>
            ))}
          </>
        ) : campaigns.length === 0 ? (
          <div className="text-center py-6 text-muted-foreground">
            No active campaigns. Create one to get started!
          </div>
        ) : (
          campaigns.map((campaign) => (
            <div
              key={campaign.id}
              className="flex items-center gap-4 p-3 rounded-lg border"
            >
              <div className="flex-1 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{campaign.name}</span>
                    <Badge
                      variant="outline"
                      className={
                        campaign.status === "running"
                          ? "bg-success/10 text-success border-success/20"
                          : "bg-info/10 text-info border-info/20"
                      }
                    >
                      {campaign.status}
                    </Badge>
                  </div>
                  <span className="text-sm text-muted-foreground">
                    {campaign.sent}/{campaign.total}
                  </span>
                </div>
                <Progress value={campaign.progress} className="h-2" />
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
});

interface AgentsCardProps {
  agents: AgentStat[];
  isPending: boolean;
}

export const AgentsCard = memo(function AgentsCard({
  agents,
  isPending,
}: AgentsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 gradient-heading">
          <Bot className="size-5" />
          AI Agents
        </CardTitle>
        <CardDescription>Performance this week</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isPending ? (
          <>
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Skeleton className="size-8 rounded-full" />
                  <div>
                    <Skeleton className="h-4 w-20 mb-1" />
                    <Skeleton className="h-3 w-16" />
                  </div>
                </div>
                <div className="text-right">
                  <Skeleton className="h-4 w-12 mb-1" />
                  <Skeleton className="h-3 w-8" />
                </div>
              </div>
            ))}
          </>
        ) : agents.length === 0 ? (
          <div className="text-center py-6 text-muted-foreground">
            No agents configured yet.
          </div>
        ) : (
          agents.map((agent, index) => (
            <div key={agent.id} className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex size-8 items-center justify-center rounded-full bg-primary/10 text-sm font-medium">
                  {index + 1}
                </div>
                <div>
                  <p className="font-medium">{agent.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {agent.calls} calls, {agent.messages} messages
                  </p>
                </div>
              </div>
              <div className="text-right">
                <p className="font-medium text-success">
                  {agent.success_rate}%
                </p>
                <p className="text-xs text-muted-foreground">success</p>
              </div>
            </div>
          ))
        )}
        <Button variant="outline" className="w-full" asChild>
          <Link href="/agents">Manage Agents</Link>
        </Button>
      </CardContent>
    </Card>
  );
});
