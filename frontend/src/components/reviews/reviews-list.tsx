"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, Loader2, Check, MessageSquare } from "lucide-react";
import { useState } from "react";

import { StarRating } from "@/components/reviews/star-rating";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { reviewsApi, type UpdateReviewPayload } from "@/lib/api/reviews";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { Review, ReviewSentiment } from "@/types/review";

const sentimentStyles: Record<ReviewSentiment, string> = {
  positive: "bg-success/10 text-success",
  neutral: "bg-muted text-muted-foreground",
  negative: "bg-destructive/10 text-destructive",
};

function ReviewCard({ review }: { review: Review }) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(review.reply_draft ?? "");

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.reviews.all(workspaceId ?? ""),
    });
    queryClient.invalidateQueries({
      queryKey: queryKeys.reviews.summary(workspaceId ?? ""),
    });
  };

  const generateMutation = useMutation({
    mutationFn: () => reviewsApi.generateReply(workspaceId!, review.id),
    onSuccess: (result) => {
      if (result.reply) setDraft(result.reply);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: UpdateReviewPayload) =>
      reviewsApi.update(workspaceId!, review.id, data),
    onSuccess: invalidate,
  });

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <StarRating value={review.rating} />
            <Badge
              variant="secondary"
              className={cn(sentimentStyles[review.sentiment])}
            >
              {review.sentiment}
            </Badge>
            {review.is_public ? (
              <Badge variant="outline" className="text-success border-success/30">
                Public
              </Badge>
            ) : (
              <Badge variant="outline" className="text-warning border-warning/30">
                Private feedback
              </Badge>
            )}
            <Badge variant="outline">{review.status}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            {review.reviewer_name || review.contact_name || "Anonymous"} ·{" "}
            {review.source.replace("_", " ")}
          </p>
        </div>
      </div>

      {review.body && (
        <p className="text-sm whitespace-pre-wrap">{review.body}</p>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Reply draft
          </span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => generateMutation.mutate()}
            disabled={generateMutation.isPending}
          >
            {generateMutation.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            <span className="ml-1">AI draft</span>
          </Button>
        </div>
        {generateMutation.isError && (
          <p className="text-xs text-destructive">
            Couldn&apos;t generate a reply. Check your OpenAI integration.
          </p>
        )}
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Write or generate an on-brand reply…"
          rows={3}
        />
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => updateMutation.mutate({ reply_draft: draft })}
            disabled={updateMutation.isPending}
          >
            <MessageSquare className="size-4" />
            <span className="ml-1">Save draft</span>
          </Button>
          <Button
            size="sm"
            onClick={() =>
              updateMutation.mutate({
                reply_draft: draft,
                reply_sent: true,
                status: "replied",
              })
            }
            disabled={updateMutation.isPending || !draft.trim()}
          >
            <Check className="size-4" />
            <span className="ml-1">Mark replied</span>
          </Button>
          {!review.is_public && review.status !== "resolved" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => updateMutation.mutate({ status: "resolved" })}
              disabled={updateMutation.isPending}
            >
              Resolve
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export function ReviewsList({ isPublic }: { isPublic?: boolean }) {
  const workspaceId = useWorkspaceId();

  const params = isPublic === undefined ? {} : { is_public: isPublic };

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.reviews.list(workspaceId ?? "", params),
    queryFn: () => reviewsApi.list(workspaceId!, params),
    enabled: !!workspaceId,
  });

  if (isPending) {
    return <PageLoadingState message="Loading reviews…" />;
  }

  if (isError) {
    return (
      <PageErrorState
        message="We couldn't load reviews. Please try again."
        onRetry={() => refetch()}
      />
    );
  }

  const reviews = data?.items ?? [];

  if (reviews.length === 0) {
    return (
      <PageEmptyState
        title="No reviews yet"
        description="Reviews appear here once customers respond to review requests."
      />
    );
  }

  return (
    <div className="divide-y">
      {reviews.map((review) => (
        <ReviewCard key={review.id} review={review} />
      ))}
    </div>
  );
}
