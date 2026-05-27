"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { VoiceCampaignWizard } from "@/components/campaigns/voice-campaign-wizard";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { Button } from "@/components/ui/button";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { agentsApi } from "@/lib/api/agents";
import { phoneNumbersApi } from "@/lib/api/phone-numbers";
import {
  voiceCampaignsApi,
  type CreateVoiceCampaignRequest,
} from "@/lib/api/voice-campaigns";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { VoiceCampaign } from "@/types";

export default function NewVoiceCampaignPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch phone numbers from API - filter to voice-enabled only
  const { data: phoneNumbersData, isPending: phoneNumbersLoading } = useQuery({
    queryKey: queryKeys.phoneNumbers.bare(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) return [];
      const response = await phoneNumbersApi.list(workspaceId);
      // Filter to voice-enabled only on client side
      return response.items.filter((p) => p.voice_enabled);
    },
    enabled: !!workspaceId,
  });

  // Fetch agents from API - all active agents
  const { data: agentsData, isPending: agentsLoading } = useQuery({
    queryKey: queryKeys.agents.activeOnly(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) return [];
      const response = await agentsApi.list(workspaceId, { active_only: true });
      return response.items;
    },
    enabled: !!workspaceId,
  });

  // Create campaign mutation
  const createCampaignMutation = useMutation({
    mutationFn: async ({
      data,
      contactIds,
    }: {
      data: CreateVoiceCampaignRequest;
      contactIds: Set<number>;
    }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");

      // Create the campaign
      const campaign = await voiceCampaignsApi.create(workspaceId, data);

      // Add contacts to the campaign
      const contactIdsArray = Array.from(contactIds);
      if (contactIdsArray.length > 0) {
        await voiceCampaignsApi.addContacts(workspaceId, campaign.id, {
          contact_ids: contactIdsArray,
        });
      }

      return campaign;
    },
    onSuccess: (campaign) => {
      toast.success(messages.campaigns.voiceCreated);
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.bare(workspaceId) });
        queryClient.invalidateQueries({
          queryKey: queryKeys.voiceCampaigns.bare(workspaceId),
        });
      }
      router.push(`/campaigns/${campaign.id}`);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, messages.campaigns.voiceCreateFailed));
    },
  });

  const handleSubmit = async (
    data: CreateVoiceCampaignRequest,
    contactIds: Set<number>
  ): Promise<VoiceCampaign> => {
    setIsSubmitting(true);
    try {
      const campaign = await createCampaignMutation.mutateAsync({
        data,
        contactIds,
      });
      return campaign;
    } finally {
      setIsSubmitting(false);
    }
  };

  const isPending = !workspaceId || phoneNumbersLoading || agentsLoading;

  const agents = Array.isArray(agentsData) ? agentsData : [];
  const phoneNumbers = Array.isArray(phoneNumbersData) ? phoneNumbersData : [];

  // Separate voice and text agents
  const voiceAgents = agents.filter(
    (a) => a.channel_mode === "voice" || a.channel_mode === "both"
  );
  const textAgents = agents.filter(
    (a) => a.channel_mode === "text" || a.channel_mode === "both"
  );

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
            <h1 className="text-xl font-semibold">
              Create Voice Campaign with SMS Fallback
            </h1>
            <p className="text-sm text-muted-foreground">
              Set up outbound AI calls with automatic SMS when calls fail
            </p>
          </div>
        </div>

        {/* Wizard content */}
        {isPending ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="size-8 animate-spin text-muted-foreground" />
              <p className="text-muted-foreground">Loading campaign data...</p>
            </div>
          </div>
        ) : (
          <VoiceCampaignWizard
            workspaceId={workspaceId}
            voiceAgents={voiceAgents}
            textAgents={textAgents}
            phoneNumbers={phoneNumbers}
            onSubmit={handleSubmit}
            onCancel={() => router.push("/campaigns")}
            isSubmitting={isSubmitting}
          />
        )}
      </div>
    </AppSidebar>
  );
}
