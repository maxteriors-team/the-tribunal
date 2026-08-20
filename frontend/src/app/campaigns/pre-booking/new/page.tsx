"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  PreBookingCampaignWizard,
  type PreBookingSubmission,
} from "@/components/campaigns/pre-booking-campaign-wizard";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { Button } from "@/components/ui/button";
import { PageLoadingState } from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { agentsApi } from "@/lib/api/agents";
import { offersApi } from "@/lib/api/offers";
import { phoneNumbersApi } from "@/lib/api/phone-numbers";
import { preBookingApi } from "@/lib/api/pre-booking-campaigns";
import { smsCampaignsApi } from "@/lib/api/sms-campaigns";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Offer } from "@/types";

export default function NewPreBookingCampaignPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { data: offersData, isPending: offersLoading } = useQuery({
    queryKey: queryKeys.offers.all(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) return [];
      try {
        const response = await offersApi.list(workspaceId);
        return response.items;
      } catch {
        return [];
      }
    },
    enabled: !!workspaceId,
  });

  const { data: phoneNumbersData, isPending: phoneNumbersLoading } = useQuery({
    queryKey: queryKeys.phoneNumbers.activeTextCapable(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) return [];
      const response = await phoneNumbersApi.list(workspaceId, { active_only: true });
      return response.items.filter((phone) => phone.sms_enabled || phone.imessage_enabled);
    },
    enabled: !!workspaceId,
  });

  const { data: agentsData, isPending: agentsLoading } = useQuery({
    queryKey: queryKeys.agents.activeOnly(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) return [];
      const response = await agentsApi.list(workspaceId, { active_only: true });
      return response.items;
    },
    enabled: !!workspaceId,
  });

  const createOfferMutation = useMutation({
    mutationFn: async (offer: Partial<Offer>) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      await offersApi.create(workspaceId, {
        name: offer.name!,
        description: offer.description,
        discount_type: offer.discount_type!,
        discount_value: offer.discount_value!,
        terms: offer.terms,
        is_active: offer.is_active ?? true,
      });
    },
    onSuccess: () => {
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.offers.all(workspaceId) });
      }
      toast.success(messages.offers.created);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, messages.offers.createFailed));
    },
  });

  /**
   * Four calls, in this order, because each one needs the last:
   * campaign row -> offer attached to it -> warm audience enrolled -> launch.
   *
   * The launch step is last on purpose. A campaign that starts sending before
   * its audience is enrolled would go out to nobody, and one that starts before
   * its offer exists would promise a season it cannot sell.
   */
  const createMutation = useMutation({
    mutationFn: async (submission: PreBookingSubmission) => {
      if (!workspaceId) throw new Error("Workspace not loaded");

      const campaign = await smsCampaignsApi.create(workspaceId, submission.campaign);
      await preBookingApi.createOffer(workspaceId, campaign.id, submission.offer);
      const audience = await preBookingApi.enrollAudience(
        workspaceId,
        campaign.id,
        submission.audience,
      );

      if (submission.scheduledStart) {
        await preBookingApi.scheduleLaunch(workspaceId, campaign.id, {
          scheduled_start: submission.scheduledStart,
        });
      } else if (audience.enrolled > 0) {
        await smsCampaignsApi.start(workspaceId, campaign.id);
      }

      return { campaign, audience, scheduled: !!submission.scheduledStart };
    },
    onSuccess: ({ campaign, audience, scheduled }) => {
      toast.success(
        scheduled
          ? messages.campaigns.preBookingScheduled(audience.enrolled)
          : messages.campaigns.preBookingCreated(audience.enrolled),
      );
      if (audience.excluded_opted_out > 0) {
        toast.info(messages.campaigns.preBookingOptOutsExcluded(audience.excluded_opted_out));
      }
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all(workspaceId) });
      }
      router.push(`/campaigns/${campaign.id}`);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, messages.campaigns.preBookingCreateFailed));
    },
  });

  const handleSubmit = async (submission: PreBookingSubmission) => {
    setIsSubmitting(true);
    try {
      await createMutation.mutateAsync(submission);
    } finally {
      setIsSubmitting(false);
    }
  };

  const isPending = !workspaceId || offersLoading || phoneNumbersLoading || agentsLoading;

  return (
    <AppSidebar>
      <div className="flex h-full min-h-0 min-w-0 flex-col">
        <div className="flex items-center gap-3 border-b bg-background px-4 py-4 sm:gap-4 sm:px-6">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/campaigns" aria-label="Back to campaigns">
              <ArrowLeft className="size-5" />
            </Link>
          </Button>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold">Create Pre-Booking Campaign</h1>
            <p className="text-sm text-muted-foreground">
              Sell next season&apos;s work now — a discount for a deposit, months ahead
            </p>
          </div>
        </div>

        {isPending ? (
          <PageLoadingState className="flex-1" message="Loading campaign data…" />
        ) : (
          <PreBookingCampaignWizard
            workspaceId={workspaceId}
            agents={Array.isArray(agentsData) ? agentsData : []}
            offers={Array.isArray(offersData) ? offersData : []}
            phoneNumbers={Array.isArray(phoneNumbersData) ? phoneNumbersData : []}
            onSubmit={handleSubmit}
            onCreateOffer={(offer) => createOfferMutation.mutateAsync(offer)}
            onCancel={() => router.push("/campaigns")}
            isSubmitting={isSubmitting}
          />
        )}
      </div>
    </AppSidebar>
  );
}
