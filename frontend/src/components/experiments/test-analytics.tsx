"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Trophy,
  TrendingUp,
  Users,
  MessageSquare,
  Reply,
  CheckCircle2,
  Star,
  ArrowRight,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { messageTestsApi } from "@/lib/api/message-tests";
import { queryKeys } from "@/lib/query-keys";
import { POLL_30S } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";
import type { VariantAnalytics } from "@/types";

const convertCampaignSchema = z.object({
  campaign_name: z
    .string()
    .min(1, { error: "Campaign name is required" })
    .max(255, { error: "Name must be 255 characters or less" }),
  use_winning_message: z.boolean(),
  include_remaining_contacts: z.boolean(),
});

type ConvertCampaignValues = z.infer<typeof convertCampaignSchema>;

const defaultConvertValues: ConvertCampaignValues = {
  campaign_name: "",
  use_winning_message: true,
  include_remaining_contacts: true,
};

interface TestAnalyticsProps {
  testId: string;
}

export function TestAnalytics({ testId }: TestAnalyticsProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const [showWinnerDialog, setShowWinnerDialog] = useState(false);
  const [showConvertDialog, setShowConvertDialog] = useState(false);
  const [selectedWinnerId, setSelectedWinnerId] = useState<string | null>(null);

  const convertForm = useForm<ConvertCampaignValues>({
    resolver: zodResolver(convertCampaignSchema),
    defaultValues: defaultConvertValues,
  });

  const {
    data: analytics,
    isPending,
    error,
  } = useQuery({
    queryKey: queryKeys.messageTests.analytics(workspaceId ?? "", testId),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTestsApi.getAnalytics(workspaceId, testId);
    },
    enabled: !!workspaceId && !!testId,
    ...POLL_30S,
  });

  const selectWinnerMutation = useMutation({
    mutationFn: (variantId: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTestsApi.selectWinner(workspaceId, testId, {
        variant_id: variantId,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.messageTests.analytics(workspaceId ?? "", testId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.messageTests.all(workspaceId ?? ""),
      });
      toast.success("Winner selected");
      setShowWinnerDialog(false);
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to select winner")),
  });

  const convertToCampaignMutation = useMutation({
    mutationFn: (data: ConvertCampaignValues) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTestsApi.convertToCampaign(workspaceId, testId, data);
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.messageTests.all(workspaceId ?? ""),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all(workspaceId ?? "") });
      toast.success(data.message);
      setShowConvertDialog(false);
      convertForm.reset(defaultConvertValues);
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to convert to campaign")),
  });

  const handleConvert = (data: ConvertCampaignValues) => {
    convertToCampaignMutation.mutate(data);
  };

  if (isPending) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !analytics) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2">
        <AlertCircle className="size-8 text-destructive" />
        <p className="text-muted-foreground">Failed to load analytics</p>
      </div>
    );
  }

  const getBestVariant = (): VariantAnalytics | null => {
    if (analytics.variants.length === 0) return null;
    return analytics.variants.reduce((best, v) =>
      v.response_rate > best.response_rate ? v : best
    );
  };

  const bestVariant = getBestVariant();
  const winnerVariant = analytics.winning_variant_id
    ? analytics.variants.find((v) => v.variant_id === analytics.winning_variant_id)
    : null;

  const handleSelectWinner = (variantId: string) => {
    setSelectedWinnerId(variantId);
    setShowWinnerDialog(true);
  };

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <Users className="size-4" />
              Total Contacts
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatNumber(analytics.total_contacts)}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <MessageSquare className="size-4" />
              Messages Sent
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatNumber(analytics.messages_sent)}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <Reply className="size-4" />
              Overall Response Rate
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {analytics.overall_response_rate.toFixed(1)}%
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <CheckCircle2 className="size-4" />
              Contacts Qualified
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatNumber(analytics.contacts_qualified)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Winner Banner */}
      {winnerVariant && (
        <Card className="border-success bg-success/10">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-success/10 rounded-full">
                  <Trophy className="size-6 text-success" />
                </div>
                <div>
                  <h3 className="font-semibold">
                    Winner: {winnerVariant.variant_name}
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    {winnerVariant.response_rate.toFixed(1)}% response rate
                  </p>
                </div>
              </div>
              <Button onClick={() => setShowConvertDialog(true)}>
                Convert to Campaign
                <ArrowRight className="ml-2 size-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Statistical Significance */}
      {analytics.statistical_significance && !winnerVariant && (
        <Card className="border-info bg-info/10">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <TrendingUp className="size-5 text-info" />
              <div>
                <p className="font-medium">
                  Statistical significance reached
                </p>
                <p className="text-sm text-muted-foreground">
                  You have enough data to confidently select a winner
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Variant Comparison */}
      <Card>
        <CardHeader>
          <CardTitle>Variant Performance</CardTitle>
          <CardDescription>
            Compare how each message variant is performing
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {analytics.variants.map((variant) => {
            const isBest = bestVariant?.variant_id === variant.variant_id;
            const isWinner =
              analytics.winning_variant_id === variant.variant_id;

            return (
              <div
                key={variant.variant_id}
                className={`p-4 rounded-lg border ${
                  isWinner
                    ? "border-success bg-success/10"
                    : isBest
                    ? "border-primary bg-primary/5"
                    : ""
                }`}
              >
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <h4 className="font-medium">{variant.variant_name}</h4>
                    {variant.is_control && (
                      <Badge variant="secondary">
                        <Star className="size-3 mr-1" />
                        Control
                      </Badge>
                    )}
                    {isWinner && (
                      <Badge className="bg-success">
                        <Trophy className="size-3 mr-1" />
                        Winner
                      </Badge>
                    )}
                    {isBest && !isWinner && (
                      <Badge variant="outline" className="border-primary text-primary">
                        <TrendingUp className="size-3 mr-1" />
                        Best Performing
                      </Badge>
                    )}
                  </div>
                  {!winnerVariant && analytics.status === "completed" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleSelectWinner(variant.variant_id)}
                    >
                      Select as Winner
                    </Button>
                  )}
                </div>

                <div className="grid grid-cols-4 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Contacts</p>
                    <p className="text-lg font-semibold">
                      {variant.contacts_assigned}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Sent</p>
                    <p className="text-lg font-semibold">
                      {variant.messages_sent}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Replies</p>
                    <p className="text-lg font-semibold">
                      {variant.replies_received}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Qualified</p>
                    <p className="text-lg font-semibold">
                      {variant.contacts_qualified}
                    </p>
                  </div>
                </div>

                <div className="mt-4 space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Response Rate</span>
                    <span className="font-medium">
                      {variant.response_rate.toFixed(1)}%
                    </span>
                  </div>
                  <Progress value={variant.response_rate} className="h-2" />
                </div>

                <div className="mt-2 space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">
                      Qualification Rate
                    </span>
                    <span className="font-medium">
                      {variant.qualification_rate.toFixed(1)}%
                    </span>
                  </div>
                  <Progress
                    value={variant.qualification_rate}
                    className="h-2"
                  />
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Select Winner Dialog */}
      <Dialog open={showWinnerDialog} onOpenChange={setShowWinnerDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Select Winner</DialogTitle>
            <DialogDescription>
              Selecting this variant as the winner will mark the test as having
              a winning message. You can then convert this test to a full
              campaign.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowWinnerDialog(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={() =>
                selectedWinnerId && selectWinnerMutation.mutate(selectedWinnerId)
              }
              disabled={selectWinnerMutation.isPending}
            >
              {selectWinnerMutation.isPending && (
                <Loader2 className="size-4 mr-2 animate-spin" />
              )}
              Confirm Winner
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Convert to Campaign Dialog */}
      <Dialog open={showConvertDialog} onOpenChange={setShowConvertDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Convert to Campaign</DialogTitle>
            <DialogDescription>
              Create a full SMS campaign using the winning message from this
              test.
            </DialogDescription>
          </DialogHeader>

          <Form {...convertForm}>
            <form
              onSubmit={convertForm.handleSubmit(handleConvert)}
              className="space-y-4"
            >
              <FormField
                control={convertForm.control}
                name="campaign_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Campaign Name</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., Summer Outreach Campaign"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={convertForm.control}
                name="use_winning_message"
                render={({ field }) => (
                  <FormItem className="flex items-center justify-between p-3 bg-muted/50 rounded-lg space-y-0">
                    <div>
                      <p className="font-medium text-sm">Use Winning Message</p>
                      <p className="text-xs text-muted-foreground">
                        Use the winning variant&apos;s message template
                      </p>
                    </div>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />

              <FormField
                control={convertForm.control}
                name="include_remaining_contacts"
                render={({ field }) => (
                  <FormItem className="flex items-center justify-between p-3 bg-muted/50 rounded-lg space-y-0">
                    <div>
                      <p className="font-medium text-sm">
                        Include Remaining Contacts
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Add contacts that haven&apos;t been messaged yet
                      </p>
                    </div>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowConvertDialog(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={convertToCampaignMutation.isPending}
                >
                  {convertToCampaignMutation.isPending && (
                    <Loader2 className="size-4 mr-2 animate-spin" />
                  )}
                  Create Campaign
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
