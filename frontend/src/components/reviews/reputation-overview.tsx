"use client";

import { Star } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { ReputationSummary } from "@/types/review";

function scoreColor(score: number): string {
  if (score >= 75) return "text-success";
  if (score >= 50) return "text-warning";
  return "text-destructive";
}

export function ReputationOverview({ summary }: { summary: ReputationSummary }) {
  const maxBucket = Math.max(1, ...summary.rating_distribution.map((b) => b.count));

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* Score + average */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Reputation Score
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-3">
            <span className={cn("text-4xl font-bold", scoreColor(summary.reputation_score))}>
              {summary.reputation_score}
            </span>
            <span className="text-muted-foreground mb-1">/ 100</span>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <Star className="size-4 fill-warning text-warning" />
            <span className="font-medium">{summary.average_rating.toFixed(1)}</span>
            <span className="text-sm text-muted-foreground">
              avg · {summary.total_reviews} review
              {summary.total_reviews === 1 ? "" : "s"}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Rating distribution */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Rating Distribution
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5">
          {summary.rating_distribution.map((bucket) => (
            <div key={bucket.rating} className="flex items-center gap-2">
              <span className="w-8 text-sm tabular-nums text-muted-foreground">
                {bucket.rating}★
              </span>
              <Progress
                value={(bucket.count / maxBucket) * 100}
                aria-label={`${bucket.rating}-star reviews`}
                aria-valuetext={`${bucket.count} ${bucket.count === 1 ? "review" : "reviews"}`}
                className="h-2 flex-1"
              />
              <span className="w-6 text-right text-sm tabular-nums text-muted-foreground">
                {bucket.count}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Funnel + firewall */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Request Funnel
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Requests sent</span>
            <span className="font-medium tabular-nums">{summary.requests_sent}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Response rate</span>
            <span className="font-medium tabular-nums">{summary.response_rate.toFixed(0)}%</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Public reviews</span>
            <span className="font-medium tabular-nums text-success">{summary.public_reviews}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Private feedback</span>
            <span className="font-medium tabular-nums text-warning">
              {summary.private_feedback}
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
