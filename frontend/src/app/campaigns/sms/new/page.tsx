"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { SMSCampaignWizard } from "@/components/campaigns/sms-campaign-wizard";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { Button } from "@/components/ui/button";
import { PageLoadingState } from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { agentsApi } from "@/lib/api/agents";
import { offersApi } from "@/lib/api/offers";
import { phoneNumbersApi } from "@/lib/api/phone-numbers";
import { smsCampaignsApi, type CreateSMSCampaignRequest } from "@/lib/api/sms-campaigns";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Offer, SMSCampaign } from "@/types";

export default function NewSMSCampaignPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch offers from API (with fallback to empty array)
  const { data: offersData, isPending: offersLoading } = useQuery({
    queryKey: queryKeys.offers.all(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) return [];
      try {
        const response = await offersApi.list(workspaceId);
        return response.items;
      } catch {
        // Return empty array if API not available yet
        return [];
      }
    },
    enabled: !!workspaceId,
  });

  // Fetch active text-capable sender identities. The backend includes both
  // Telnyx SMS numbers and Mac relay/iMessage senders in the active list.
  const { data: phoneNumbersData, isPending: phoneNumbersLoading } = useQuery({
    queryKey: queryKeys.phoneNumbers.activeTextCapable(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) return [];
      const response = await phoneNumbersApi.list(workspaceId, { active_only: true });
      return response.items.filter((phone) => phone.sms_enabled || phone.imessage_enabled);
    },
    enabled: !!workspaceId,
  });

  // Fetch agents from API - filter to active agents only
  const { data: agentsData, isPending: agentsLoading } = useQuery({
    queryKey: queryKeys.agents.activeOnly(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) return [];
      const response = await agentsApi.list(workspaceId, { active_only: true });
      return response.items;
    },
    enabled: !!workspaceId,
  });

  // Create offer mutation
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

  // Create campaign mutation
  const createCampaignMutation = useMutation({
    mutationFn: async ({
      data,
      contactIds,
    }: {
      data: CreateSMSCampaignRequest;
      contactIds: Set<number>;
    }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      // Create the campaign
      const campaign = await smsCampaignsApi.create(workspaceId, data);

      // Add contacts to the campaign
      const contactIdsArray = Array.from(contactIds);
      if (contactIdsArray.length > 0) {
        await smsCampaignsApi.addContacts(workspaceId, campaign.id, contactIdsArray);
      }

      return campaign;
    },
    onSuccess: (campaign) => {
      toast.success(messages.campaigns.smsCreated);
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all(workspaceId) });
      }
      router.push(`/campaigns/${campaign.id}`);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, messages.campaigns.smsCreateFailed));
    },
  });

  const handleSubmit = async (
    data: CreateSMSCampaignRequest,
    contactIds: Set<number>
  ): Promise<SMSCampaign> => {
    setIsSubmitting(true);
    try {
      const campaign = await createCampaignMutation.mutateAsync({ data, contactIds });
      return campaign as SMSCampaign;
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCreateOffer = async (offer: Partial<Offer>) => {
    await createOfferMutation.mutateAsync(offer);
  };

  const isPending = !workspaceId || offersLoading || phoneNumbersLoading || agentsLoading;

  const agents = Array.isArray(agentsData) ? agentsData : [];
  const offers = Array.isArray(offersData) ? offersData : [];
  const phoneNumbers = Array.isArray(phoneNumbersData) ? phoneNumbersData : [];

  return (
    <AppSidebar>
      <div className="flex h-full min-h-0 flex-col">
        {/* Header */}
        <div className="flex items-center gap-4 px-6 py-4 border-b bg-background">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/campaigns" aria-label="Back to campaigns">
              <ArrowLeft className="size-5" />
            </Link>
          </Button>
          <div>
            <h1 className="text-xl font-semibold">Create SMS Campaign</h1>
            <p className="text-sm text-muted-foreground">
              Set up a new SMS or iMessage campaign to reach your contacts
            </p>
          </div>
        </div>

        {/* Wizard content */}
        {isPending ? (
          <PageLoadingState className="flex-1" message="Loading campaign data…" />
        ) : (
          <SMSCampaignWizard
            workspaceId={workspaceId}
            agents={agents}
            offers={offers}
            phoneNumbers={phoneNumbers}
            onSubmit={handleSubmit}
            onCreateOffer={handleCreateOffer}
            onCancel={() => router.push("/campaigns")}
            isSubmitting={isSubmitting}
          />
        )}
      </div>
    </AppSidebar>
  );
}
