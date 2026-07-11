"use client";

import { Loader2, Users } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";

import { AppointmentPerformanceCard } from "@/components/dashboard/appointment-performance-card";
import { DashboardStatsGrid } from "@/components/dashboard/dashboard-stats";
import { KnowledgeBaseCard } from "@/components/dashboard/knowledge-base-card";
import { LeadSourceRoiCard } from "@/components/dashboard/lead-source-roi-card";
import {
  ActiveCampaignsCard,
  AgentsCard,
  AppointmentStatsCard,
} from "@/components/dashboard/performance-metrics";
import { RecentActivityFeed } from "@/components/dashboard/recent-activity-feed";
import { RevenueRoiCard } from "@/components/dashboard/revenue-roi-card";
import { ReviewsCard } from "@/components/dashboard/reviews-card";
import { RoleplayCard } from "@/components/dashboard/roleplay-card";
import { SpeedToLeadCard } from "@/components/dashboard/speed-to-lead-card";
import {
  NudgesCard,
  QuickActionsCard,
  TodayOverviewCard,
} from "@/components/dashboard/today-overview";
import { Button } from "@/components/ui/button";
import { PageErrorState } from "@/components/ui/page-state";
import { useDashboard } from "@/hooks/useDashboard";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";

export function DashboardPage() {
  const workspaceId = useWorkspaceId();
  const { data, isPending, error, isFetching, refetch } = useDashboard(
    workspaceId ?? "",
  );

  if (error && !data) {
    return (
      <PageErrorState
        className="min-h-[400px]"
        message={(error as Error).message || "Failed to load dashboard"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight gradient-heading">
            Dashboard
            {isFetching && !isPending && (
              <Loader2 className="ml-2 inline size-4 animate-spin text-muted-foreground" />
            )}
          </h1>
          <p className="text-muted-foreground">
            Welcome back! Here&apos;s an overview of your CRM activity.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" asChild>
            <Link href="/campaigns/new">New Campaign</Link>
          </Button>
          <Button asChild>
            <Link href="/contacts">
              <Users className="mr-2 size-4" />
              View Contacts
            </Link>
          </Button>
        </div>
      </div>

      <DashboardStatsGrid stats={data?.stats} isPending={isPending} />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.12 }}
      >
        <RevenueRoiCard
          revenueStats={data?.revenue_stats}
          isPending={isPending}
        />
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.13 }}
      >
        <LeadSourceRoiCard
          stats={data?.lead_source_roi_stats}
          isPending={isPending}
        />
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
      >
        <AppointmentStatsCard
          appointmentStats={data?.appointment_stats}
          isPending={isPending}
        />
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.16 }}
      >
        <SpeedToLeadCard
          speedToLeadStats={data?.speed_to_lead_stats}
          isPending={isPending}
        />
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-2">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.18 }}
        >
          <ReviewsCard reviewsStats={data?.reviews_stats} isPending={isPending} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.19 }}
        >
          <RoleplayCard
            roleplayStats={data?.roleplay_stats}
            isPending={isPending}
          />
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <KnowledgeBaseCard
          knowledgeBaseStats={data?.knowledge_base_stats}
          isPending={isPending}
        />
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-3">
        <motion.div
          className="lg:col-span-2"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <ActiveCampaignsCard
            campaigns={data?.campaign_stats ?? []}
            isPending={isPending}
          />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <AgentsCard agents={data?.agent_stats ?? []} isPending={isPending} />
        </motion.div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          <RecentActivityFeed
            activities={data?.recent_activity ?? []}
            isPending={isPending}
          />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="space-y-6"
        >
          <TodayOverviewCard
            overview={data?.today_overview}
            isPending={isPending}
          />
          <NudgesCard workspaceId={workspaceId} />
          <QuickActionsCard />
        </motion.div>
      </div>

      {workspaceId && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
        >
          <AppointmentPerformanceCard workspaceId={workspaceId} />
        </motion.div>
      )}
    </div>
  );
}
