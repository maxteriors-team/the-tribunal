"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Star } from "lucide-react";
import { use, useState } from "react";

import { StarRating } from "@/components/reviews/star-rating";
import { DeadPublicLink } from "@/components/shared/dead-public-link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { PageLoadingState } from "@/components/ui/page-state";
import { Textarea } from "@/components/ui/textarea";
import { publicReviewsApi } from "@/lib/api/public-reviews";
import { queryKeys } from "@/lib/query-keys";
import type { PublicRatingResult } from "@/types/review";

interface PublicReviewPageProps {
  params: Promise<{ token: string }>;
}

export default function PublicReviewPage({ params }: PublicReviewPageProps) {
  const { token } = use(params);

  const [selectedRating, setSelectedRating] = useState(0);
  const [submittedGate, setSubmittedGate] = useState<PublicRatingResult | null>(
    null,
  );
  const [feedback, setFeedback] = useState("");
  const [feedbackName, setFeedbackName] = useState("");
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.publicReviews.byToken(token),
    queryFn: () => publicReviewsApi.get(token),
    enabled: !!token,
    retry: false,
  });

  const rateMutation = useMutation({
    mutationFn: (rating: number) => publicReviewsApi.rate(token, rating),
    onSuccess: (result) => {
      setSubmittedGate(result);
      // Positive ratings with a configured destination redirect out.
      if (result.is_positive && result.redirect_url) {
        window.location.href = result.redirect_url;
      }
    },
  });

  const feedbackMutation = useMutation({
    mutationFn: () =>
      publicReviewsApi.submitFeedback(token, feedback, feedbackName || undefined),
    onSuccess: () => setFeedbackSubmitted(true),
  });

  const handleSelect = (rating: number) => {
    setSelectedRating(rating);
    rateMutation.mutate(rating);
  };

  // Derive the gate during render: a fresh submission wins, otherwise fall back
  // to an "already responded" gate when the request was previously completed.
  const gate: PublicRatingResult | null =
    submittedGate ??
    (data?.already_submitted
      ? {
          success: true,
          rating: data.rating ?? 0,
          is_positive: (data.rating ?? 0) >= data.positive_threshold,
          redirect_url: null,
          show_feedback_form: false,
          message: "Thanks — you've already responded.",
        }
      : null);

  if (isPending) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background to-muted">
        <PageLoadingState className="min-h-screen" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <DeadPublicLink subject="review request" />
    );
  }

  const businessName = data.business_name || "us";

  const showFeedbackForm = gate?.show_feedback_form && !feedbackSubmitted;
  const showThanks =
    (gate && !gate.show_feedback_form) || feedbackSubmitted;

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background to-muted p-4">
      <Card className="max-w-md w-full">
        {showThanks ? (
          <CardContent className="pt-6 text-center space-y-3">
            <CheckCircle2 className="size-16 text-success mx-auto" />
            <h1 className="text-2xl font-bold">Thank you!</h1>
            <p className="text-muted-foreground">
              {feedbackSubmitted
                ? "We appreciate your feedback and will be in touch."
                : gate?.message ??
                  "Thanks for letting us know how we did."}
            </p>
          </CardContent>
        ) : showFeedbackForm ? (
          <>
            <CardHeader className="text-center">
              <CardTitle>How can we do better?</CardTitle>
              <p className="text-sm text-muted-foreground">
                Your feedback goes straight to the {businessName} team — not a
                public page.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-center">
                <StarRating value={selectedRating} size="md" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="name">Your name (optional)</Label>
                <input
                  id="name"
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                  value={feedbackName}
                  onChange={(e) => setFeedbackName(e.target.value)}
                  placeholder="Jane Doe"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="feedback">What went wrong?</Label>
                <Textarea
                  id="feedback"
                  rows={4}
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="Tell us what happened so we can make it right…"
                />
              </div>
              <Button
                className="w-full"
                onClick={() => feedbackMutation.mutate()}
                disabled={!feedback.trim() || feedbackMutation.isPending}
              >
                {feedbackMutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  "Send feedback"
                )}
              </Button>
            </CardContent>
          </>
        ) : (
          <>
            <CardHeader className="text-center">
              <Star className="size-10 text-warning mx-auto fill-warning" />
              <CardTitle className="mt-2">
                {data.contact_first_name
                  ? `Hi ${data.contact_first_name}!`
                  : "How did we do?"}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Rate your experience with {businessName}.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-center py-4">
                <StarRating
                  value={selectedRating}
                  size="lg"
                  onChange={handleSelect}
                />
              </div>
              {rateMutation.isPending && (
                <div className="flex justify-center">
                  <Loader2 className="size-5 animate-spin text-muted-foreground" />
                </div>
              )}
              {rateMutation.isError && (
                <p className="text-center text-sm text-destructive">
                  Something went wrong. Please try again.
                </p>
              )}
            </CardContent>
          </>
        )}
      </Card>
    </div>
  );
}
