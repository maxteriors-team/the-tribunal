"use client";

import { ArrowUpRight, CheckCircle2, Dumbbell, Gauge, History } from "lucide-react";
import Link from "next/link";
import { memo } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { RoleplayStats } from "@/lib/api/dashboard";

interface RoleplayCardProps {
  roleplayStats: RoleplayStats | undefined;
  isPending: boolean;
}

export const RoleplayCard = memo(function RoleplayCard({
  roleplayStats,
  isPending,
}: RoleplayCardProps) {
  const avgScore = roleplayStats?.avg_overall_score ?? null;

  const scoreColor =
    avgScore === null
      ? "text-muted-foreground"
      : avgScore >= 80
        ? "text-success"
        : avgScore >= 60
          ? "text-warning"
          : "text-destructive";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="flex items-center gap-2 gradient-heading">
            <Dumbbell className="size-5" />
            Practice Arena
          </CardTitle>
          <CardDescription>Roleplay rehearsals and scoring</CardDescription>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/agents/practice">
            Practice
            <ArrowUpRight className="ml-2 size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {isPending && !roleplayStats ? (
            <>
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="space-y-1 text-center">
                  <Skeleton className="mx-auto h-8 w-12" />
                  <Skeleton className="mx-auto h-3 w-16" />
                  <Skeleton className="mx-auto h-3 w-20" />
                </div>
              ))}
            </>
          ) : (
            <>
              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-primary">
                  <Dumbbell className="size-4" />
                  <span className="text-2xl font-bold">
                    {roleplayStats?.total_runs ?? 0}
                  </span>
                </div>
                <p className="text-xs font-medium">Total Runs</p>
                <p className="text-xs text-muted-foreground">
                  {roleplayStats?.runs_this_week ?? 0} this week
                </p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-info">
                  <CheckCircle2 className="size-4" />
                  <span className="text-2xl font-bold">
                    {roleplayStats?.completed_runs ?? 0}
                  </span>
                </div>
                <p className="text-xs font-medium">Completed</p>
                <p className="text-xs text-muted-foreground">Scored</p>
              </div>

              <div className="space-y-1 text-center">
                <div className={`flex items-center justify-center gap-1 ${scoreColor}`}>
                  <Gauge className="size-4" />
                  <span className="text-2xl font-bold">
                    {avgScore !== null ? avgScore.toFixed(1) : "—"}
                  </span>
                </div>
                <p className="text-xs font-medium">Avg Score</p>
                <p className="text-xs text-muted-foreground">Overall</p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-muted-foreground">
                  <History className="size-4" />
                  <span className="text-base font-bold">
                    {roleplayStats?.last_run_at ?? "—"}
                  </span>
                </div>
                <p className="text-xs font-medium">Last Run</p>
                <p className="text-xs text-muted-foreground">Most recent</p>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
