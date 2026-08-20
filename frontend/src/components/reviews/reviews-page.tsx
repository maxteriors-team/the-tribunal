"use client";

import { useQuery } from "@tanstack/react-query";
import { Star, MessageSquareWarning, ShieldCheck, Send } from "lucide-react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { ReputationOverview } from "@/components/reviews/reputation-overview";
import { ReviewRequestsTab } from "@/components/reviews/review-requests-tab";
import { ReviewsList } from "@/components/reviews/reviews-list";
import { Card, CardContent } from "@/components/ui/card";
import { HorizontalScroll } from "@/components/ui/horizontal-scroll";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { reviewsApi } from "@/lib/api/reviews";
import { queryKeys } from "@/lib/query-keys";
import { REALTIME } from "@/lib/query-options";

export function ReviewsPage() {
  const workspaceId = useWorkspaceId();

  const {
    data: summary,
    isPending,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.reviews.summary(workspaceId ?? ""),
    queryFn: () => reviewsApi.getSummary(workspaceId!),
    enabled: !!workspaceId,
    ...REALTIME,
  });

  return (
    <AppSidebar>
      <div className="space-y-6 p-4 sm:p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Reviews &amp; Reputation</h1>
            <p className="text-muted-foreground">
              Collect reviews after completed jobs, route unhappy customers to private feedback, and
              reply on-brand.
            </p>
          </div>
        </div>

        {isPending ? (
          <PageLoadingState message="Loading reputation…" />
        ) : error || !summary ? (
          <PageErrorState message="Failed to load reputation data." onRetry={() => refetch()} />
        ) : (
          <ReputationOverview summary={summary} />
        )}

        <Tabs defaultValue="reviews" className="space-y-4">
          <HorizontalScroll
            activeKey="reviews"
            aria-label="Review sections, scroll horizontally"
            data-testid="reviews-tabs-scroll"
          >
            <TabsList className="h-auto w-max min-w-full justify-start">
              <TabsTrigger value="reviews" className="gap-2">
                <Star className="size-4" />
                Reviews
              </TabsTrigger>
              <TabsTrigger value="feedback" className="gap-2">
                <MessageSquareWarning className="size-4" />
                Private Feedback
              </TabsTrigger>
              <TabsTrigger value="public" className="gap-2">
                <ShieldCheck className="size-4" />
                Public
              </TabsTrigger>
              <TabsTrigger value="requests" className="gap-2">
                <Send className="size-4" />
                Requests
              </TabsTrigger>
            </TabsList>
          </HorizontalScroll>

          <TabsContent value="reviews">
            <Card>
              <CardContent className="p-0">
                <ReviewsList />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="feedback">
            <Card>
              <CardContent className="p-0">
                <ReviewsList isPublic={false} />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="public">
            <Card>
              <CardContent className="p-0">
                <ReviewsList isPublic={true} />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="requests">
            <Card>
              <CardContent className="p-0">
                <ReviewRequestsTab />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </AppSidebar>
  );
}
