"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { reviewsApi } from "@/lib/api/reviews";
import { queryKeys } from "@/lib/query-keys";
import type { UpdateReviewSettings } from "@/types/review";

export function ReviewSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: settings, isPending } = useQuery({
    queryKey: queryKeys.reviews.settings(workspaceId ?? ""),
    queryFn: () => reviewsApi.getSettings(workspaceId!),
    enabled: !!workspaceId,
  });

  const mutation = useSettingsSaveMutation({
    mutationFn: (data: UpdateReviewSettings) => reviewsApi.updateSettings(workspaceId!, data),
    successMessage: "Review request settings are up to date.",
    errorMessage: "We couldn't save review request settings. Check your connection and try again.",
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.reviews.settings(workspaceId ?? ""),
      });
    },
  });

  const update = (data: UpdateReviewSettings) => mutation.mutate(data);

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const enabled = settings?.enabled ?? false;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Reputation Engine</CardTitle>
          <CardDescription>
            Automatically request reviews after completed appointments. Happy customers are sent to
            your public review page; unhappy ones are routed to a private feedback form.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="reputation-engine-enabled">Enable reputation engine</Label>
              <p className="text-sm text-muted-foreground">
                Master switch for review requests and collection
              </p>
            </div>
            <Switch
              id="reputation-engine-enabled"
              checked={enabled}
              onCheckedChange={(checked) => update({ enabled: checked })}
              disabled={mutation.isPending}
            />
          </div>

          {enabled && (
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="review-auto-request">Auto-request after completed jobs</Label>
                <p className="text-sm text-muted-foreground">
                  Send a review request when an appointment is marked completed
                </p>
              </div>
              <Switch
                id="review-auto-request"
                checked={settings?.auto_request_on_completion ?? true}
                onCheckedChange={(checked) => update({ auto_request_on_completion: checked })}
                disabled={mutation.isPending}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Rating Gate</CardTitle>
            <CardDescription>
              Choose the minimum star rating that routes a customer to your public review page.
              Lower ratings go to private feedback.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="review-positive-threshold">Positive threshold</Label>
              <Select
                value={String(settings?.positive_threshold ?? 4)}
                onValueChange={(value) => update({ positive_threshold: Number(value) })}
              >
                <SelectTrigger id="review-positive-threshold" className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="3">3 stars and up</SelectItem>
                  <SelectItem value="4">4 stars and up</SelectItem>
                  <SelectItem value="5">5 stars only</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="google-url">Google review URL</Label>
              <Input
                id="google-url"
                placeholder="https://g.page/r/…/review"
                defaultValue={settings?.google_review_url ?? ""}
                onBlur={(e) => update({ google_review_url: e.target.value || null })}
                disabled={mutation.isPending}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="facebook-url">Facebook review URL</Label>
              <Input
                id="facebook-url"
                placeholder="https://facebook.com/…/reviews"
                defaultValue={settings?.facebook_review_url ?? ""}
                onBlur={(e) => update({ facebook_review_url: e.target.value || null })}
                disabled={mutation.isPending}
              />
            </div>

            {!settings?.google_review_url && !settings?.facebook_review_url && (
              <Alert>
                <Info className="size-4" />
                <AlertDescription>
                  Add at least one public review URL so positive ratings have somewhere to go.
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}

      {enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Message &amp; Timing</CardTitle>
            <CardDescription>Customize the review-request SMS and when it is sent.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="business-name">Business name</Label>
              <Input
                id="business-name"
                placeholder="Acme Plumbing"
                defaultValue={settings?.business_name ?? ""}
                onBlur={(e) => update({ business_name: e.target.value || null })}
                disabled={mutation.isPending}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="template">Request message template</Label>
              <Textarea
                id="template"
                rows={3}
                placeholder="Hi {first_name}, thanks for choosing {business_name}! How did we do? {link}"
                defaultValue={settings?.request_message_template ?? ""}
                onBlur={(e) => update({ request_message_template: e.target.value || null })}
                disabled={mutation.isPending}
              />
              <p className="text-xs text-muted-foreground">
                Placeholders: {"{first_name}"}, {"{business_name}"}, {"{link}"}. The link is added
                automatically if you omit it.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="delay">Send delay (minutes after completion)</Label>
              <Input
                id="delay"
                type="number"
                min={0}
                max={10080}
                className="w-32"
                defaultValue={settings?.request_delay_minutes ?? 60}
                onBlur={(e) => {
                  const val = Number(e.target.value);
                  if (val >= 0 && val <= 10080) update({ request_delay_minutes: val });
                }}
                disabled={mutation.isPending}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="tone">AI reply tone / brand voice</Label>
              <Input
                id="tone"
                placeholder="Warm, concise, professional"
                defaultValue={settings?.reply_tone ?? ""}
                onBlur={(e) => update({ reply_tone: e.target.value || null })}
                disabled={mutation.isPending}
              />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
