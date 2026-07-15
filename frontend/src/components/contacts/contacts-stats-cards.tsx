"use client";

import { ArrowRight, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";

import { isTrendUp } from "@/components/dashboard/animations";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ContactStatsResponse } from "@/lib/api/contacts";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils/number";

interface MetricCardProps {
  title: string;
  timeframe: string;
  value: number;
  /** Preformatted change string (e.g. "+24%"); omit for cards with no trend. */
  change?: string;
}

function MetricCard({ title, timeframe, value, change }: MetricCardProps) {
  const trendUp = change ? isTrendUp(change) : false;

  return (
    <Card>
      <CardHeader className="gap-1 pb-2">
        <CardDescription className="text-foreground text-sm font-semibold">
          {title}
        </CardDescription>
        <span className="text-muted-foreground text-xs">{timeframe}</span>
      </CardHeader>
      <CardContent>
        <div className="flex items-end justify-between gap-2">
          <span className="text-3xl font-bold tabular-nums">{formatNumber(value)}</span>
          {change ? (
            <span
              className={cn(
                "flex items-center gap-0.5 text-sm font-medium",
                trendUp ? "text-success" : "text-destructive",
              )}
            >
              {trendUp ? (
                <TrendingUp className="size-4" />
              ) : (
                <TrendingDown className="size-4" />
              )}
              {change}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function PromoCard() {
  return (
    <Link href="/automations" className="group">
      <Card className="from-primary/10 hover:border-primary/40 h-full bg-gradient-to-br to-transparent">
        <CardHeader className="gap-1 pb-2">
          <div className="bg-primary/10 ring-primary/20 w-fit rounded-lg p-2 ring-1">
            <Sparkles className="text-primary size-4" />
          </div>
        </CardHeader>
        <CardContent className="space-y-1">
          <p className="text-sm font-semibold">Put follow-up on autopilot</p>
          <p className="text-muted-foreground group-hover:text-foreground flex items-center gap-1 text-xs transition-colors">
            Explore automations
            <ArrowRight className="size-3 transition-transform group-hover:translate-x-0.5" />
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

function StatCardSkeleton() {
  return (
    <Card>
      <CardHeader className="gap-1 pb-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-3 w-16" />
      </CardHeader>
      <CardContent>
        <div className="flex items-end justify-between">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-4 w-12" />
        </div>
      </CardContent>
    </Card>
  );
}

interface ContactsStatsCardsProps {
  stats: ContactStatsResponse | undefined;
  isPending: boolean;
}

export function ContactsStatsCards({ stats, isPending }: ContactsStatsCardsProps) {
  if (isPending) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3].map((i) => (
          <StatCardSkeleton key={i} />
        ))}
        <PromoCard />
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <MetricCard
        title="New leads"
        timeframe="Past 30 days"
        value={stats.new_leads_30d}
        change={stats.new_leads_change}
      />
      <MetricCard
        title="New clients"
        timeframe="Past 30 days"
        value={stats.new_clients_30d}
        change={stats.new_clients_change}
      />
      <MetricCard
        title="Total new clients"
        timeframe="Year to date"
        value={stats.total_new_clients_ytd}
      />
      <PromoCard />
    </div>
  );
}
