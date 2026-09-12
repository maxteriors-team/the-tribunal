"use client";

import { ArrowRight, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";

import { isTrendUp } from "@/components/dashboard/animations";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ContactStatsResponse } from "@/lib/api/contacts";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils/number";
import type { FilterDefinition } from "@/types";

interface MetricCardProps {
  title: string;
  timeframe: string;
  value: number;
  /** Null means an undefined zero baseline; omit for cards without comparisons. */
  change?: string | null;
  onView: () => void;
}

function MetricCard({ title, timeframe, value, change, onView }: MetricCardProps) {
  const trendUp = change ? isTrendUp(change) : false;

  return (
    <Card>
      <CardHeader className="gap-1 pb-2">
        <CardDescription className="text-foreground text-sm font-semibold">{title}</CardDescription>
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
              {trendUp ? <TrendingUp className="size-4" /> : <TrendingDown className="size-4" />}
              {change}
            </span>
          ) : change === null ? (
            <span className="text-muted-foreground text-sm">No baseline</span>
          ) : null}
        </div>
        <Button
          variant="link"
          size="sm"
          className="h-auto px-0 pt-3"
          aria-label={`View ${title.toLowerCase()}, ${timeframe.toLowerCase()}`}
          onClick={onView}
        >
          View contacts
        </Button>
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
  onViewContacts: (filters: FilterDefinition) => void;
}

export function ContactsStatsCards({ stats, isPending, onViewContacts }: ContactsStatsCardsProps) {
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

  const viewContacts = (start: string, convertedOnly = false) => {
    onViewContacts({
      logic: "and",
      rules: [
        { field: "created_at", operator: "gte", value: start },
        { field: "created_at", operator: "lt", value: stats.period_end },
        ...(convertedOnly ? [{ field: "status", operator: "equals", value: "converted" }] : []),
      ],
    });
  };

  return (
    <div className="space-y-2">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Contacts created"
          timeframe="Past 30 days"
          value={stats.new_leads_30d}
          change={stats.new_leads_change}
          onView={() => viewContacts(stats.period_start)}
        />
        <MetricCard
          title="Converted contacts"
          timeframe="Created in past 30 days"
          value={stats.new_clients_30d}
          change={stats.new_clients_change}
          onView={() => viewContacts(stats.period_start, true)}
        />
        <MetricCard
          title="Converted contacts"
          timeframe="Created year to date"
          value={stats.total_new_clients_ytd}
          onView={() => viewContacts(stats.year_start, true)}
        />
        <PromoCard />
      </div>
      <p className="text-muted-foreground text-xs">
        Workspace-wide, independent of list filters. Converted contacts are currently converted,
        grouped by creation date—not conversion date. Conversion dates and reconversions are not
        recorded. Changes compare the prior 30-day creation cohort. Year to date uses{" "}
        {stats.timezone}.
      </p>
    </div>
  );
}
