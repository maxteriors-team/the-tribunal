"use client";

import { ArrowUpRight, MessageSquareWarning, Send, Star } from "lucide-react";
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
import type { ReviewsStats } from "@/lib/api/dashboard";

interface ReviewsCardProps {
  reviewsStats: ReviewsStats | undefined;
  isPending: boolean;
}

export const ReviewsCard = memo(function ReviewsCard({
  reviewsStats,
  isPending,
}: ReviewsCardProps) {
  const avg = reviewsStats?.average_rating ?? 0;
  const score = reviewsStats?.reputation_score ?? 0;

  const scoreColor =
    score >= 75
      ? "text-success"
      : score >= 50
        ? "text-warning"
        : "text-destructive";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="flex items-center gap-2 gradient-heading">
            <Star className="size-5" />
            Reviews &amp; Reputation
          </CardTitle>
          <CardDescription>Customer sentiment and review funnel</CardDescription>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/reviews">
            View Reviews
            <ArrowUpRight className="ml-2 size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {isPending && !reviewsStats ? (
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
                <div className="flex items-center justify-center gap-1 text-warning">
                  <Star className="size-4 fill-current" />
                  <span className="text-2xl font-bold">
                    {avg > 0 ? avg.toFixed(1) : "—"}
                  </span>
                </div>
                <p className="text-xs font-medium">Avg Rating</p>
                <p className="text-xs text-muted-foreground">
                  {reviewsStats?.total_reviews ?? 0} reviews
                </p>
              </div>

              <div className="space-y-1 text-center">
                <div className={`flex items-center justify-center gap-1 ${scoreColor}`}>
                  <span className="text-2xl font-bold">{score}</span>
                </div>
                <p className="text-xs font-medium">Reputation</p>
                <p className="text-xs text-muted-foreground">Score / 100</p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-info">
                  <Send className="size-4" />
                  <span className="text-2xl font-bold">
                    {reviewsStats
                      ? `${reviewsStats.response_rate}%`
                      : "—"}
                  </span>
                </div>
                <p className="text-xs font-medium">Response Rate</p>
                <p className="text-xs text-muted-foreground">
                  {reviewsStats?.requests_rated ?? 0}/
                  {reviewsStats?.requests_sent ?? 0} rated
                </p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-destructive">
                  <MessageSquareWarning className="size-4" />
                  <span className="text-2xl font-bold">
                    {reviewsStats?.private_feedback ?? 0}
                  </span>
                </div>
                <p className="text-xs font-medium">Private Feedback</p>
                <p className="text-xs text-muted-foreground">
                  {reviewsStats?.new_count ?? 0} new
                </p>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
