import type React from "react";
import { memo } from "react";
import Link from "next/link";
import { motion } from "motion/react";
import {
  Megaphone,
  MessageSquare,
  Phone,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AnimatedNumber,
  containerVariants,
  isTrendUp,
  itemVariants,
} from "@/components/dashboard/animations";
import type { DashboardStats } from "@/lib/api/dashboard";

interface StatCardProps {
  title: string;
  value: number;
  change: string;
  href: string;
  icon: React.ReactNode;
}

function StatCard({ title, value, change, href, icon }: StatCardProps) {
  const trendUp = isTrendUp(change);

  return (
    <Link href={href}>
      <Card className="card-glow card-interactive hover:bg-muted/50 transition-colors cursor-pointer">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardDescription>{title}</CardDescription>
          <div className="rounded-lg bg-primary/10 p-2 ring-1 ring-primary/20">
            {icon}
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div className="text-2xl font-bold tabular-nums">
              <AnimatedNumber value={value} />
            </div>
            <div
              className={`flex items-center text-sm ${
                trendUp ? "text-success" : "text-destructive"
              }`}
            >
              {trendUp ? (
                <TrendingUp className="mr-1 size-4" />
              ) : (
                <TrendingDown className="mr-1 size-4" />
              )}
              {change}
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

function StatCardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="size-4 rounded" />
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-4 w-12" />
        </div>
      </CardContent>
    </Card>
  );
}

interface DashboardStatsGridProps {
  stats: DashboardStats | undefined;
  isPending: boolean;
}

export const DashboardStatsGrid = memo(function DashboardStatsGrid({
  stats,
  isPending,
}: DashboardStatsGridProps) {
  if (isPending) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <StatCardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (!stats) return null;

  return (
    <motion.div
      className="grid gap-4 md:grid-cols-2 lg:grid-cols-4"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.div variants={itemVariants}>
        <StatCard
          title="Total Contacts"
          value={stats.total_contacts}
          change={stats.contacts_change}
          href="/contacts"
          icon={<Users className="size-4 text-primary" />}
        />
      </motion.div>
      <motion.div variants={itemVariants}>
        <StatCard
          title="Active Campaigns"
          value={stats.active_campaigns}
          change={stats.campaigns_change}
          href="/campaigns"
          icon={<Megaphone className="size-4 text-primary" />}
        />
      </motion.div>
      <motion.div variants={itemVariants}>
        <StatCard
          title="Calls Today"
          value={stats.calls_today}
          change={stats.calls_change}
          href="/calls"
          icon={<Phone className="size-4 text-primary" />}
        />
      </motion.div>
      <motion.div variants={itemVariants}>
        <StatCard
          title="Messages Sent"
          value={stats.messages_sent}
          change={stats.messages_change}
          href="/campaigns"
          icon={<MessageSquare className="size-4 text-primary" />}
        />
      </motion.div>
    </motion.div>
  );
});
