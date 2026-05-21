import { campaignsApi } from "@/lib/api/campaigns";
import { contactsApi } from "@/lib/api/contacts";
import type { AgentStat } from "@/lib/api/dashboard";
import { offersApi } from "@/lib/api/offers";
import { pendingActionsApi } from "@/lib/api/pending-actions";
import { segmentsApi } from "@/lib/api/segments";
import type { Campaign, Offer, Segment } from "@/types";
import type { PendingAction } from "@/types/pending-action";

const MAX_ITEMS = 100;

export interface PerformanceRow {
  id: string;
  name: string;
  audience: number;
  responses: number;
  qualified: number;
  optOuts: number;
  conversionRate: number;
  source: "offer" | "segment" | "angle";
}

export interface WarmLeadAction {
  id: string;
  description: string;
  urgency: string;
  actionType: string;
  createdAt: string;
  contactName?: string;
}

export interface CampaignHealthRow {
  id: string;
  name: string;
  status: Campaign["status"];
  sent: number;
  total: number;
  deliveryRate: number;
  responseRate: number;
  failureRate: number;
  health: "healthy" | "watch" | "critical";
}

export interface OptOutSummary {
  total: number;
  rate: number;
  byCampaign: Array<{
    id: string;
    name: string;
    optOuts: number;
    rate: number;
  }>;
}

export interface OutboundGrowthAnalyticsResponse {
  offerPerformance: PerformanceRow[];
  segmentPerformance: PerformanceRow[];
  anglePerformance: PerformanceRow[];
  warmLeadActions: WarmLeadAction[];
  campaignHealth: CampaignHealthRow[];
  optOuts: OptOutSummary;
  aiResponderPerformance: AgentStat[];
  totals: {
    campaigns: number;
    activeCampaigns: number;
    warmLeads: number;
    qualified: number;
    replies: number;
  };
}

function percentage(numerator: number, denominator: number) {
  if (denominator <= 0) return 0;
  return Math.round((numerator / denominator) * 100);
}

function actionContactName(action: PendingAction) {
  const contact = action.context.contact;
  if (typeof contact === "string") return contact;

  const contactName = action.context.contact_name;
  if (typeof contactName === "string") return contactName;

  const leadName = action.context.lead_name;
  if (typeof leadName === "string") return leadName;

  return undefined;
}

function buildCampaignHealth(campaigns: Campaign[]): CampaignHealthRow[] {
  return campaigns
    .map((campaign) => {
      const deliveryRate = percentage(campaign.messages_delivered, campaign.messages_sent);
      const responseRate = percentage(campaign.replies_received, campaign.messages_sent);
      const failureRate = percentage(campaign.messages_failed, campaign.messages_sent);
      const progress = percentage(campaign.messages_sent, campaign.total_contacts);
      const health: CampaignHealthRow["health"] =
        failureRate >= 15 || campaign.status === "cancelled"
          ? "critical"
          : failureRate >= 8 || (campaign.status === "running" && progress < 20)
            ? "watch"
            : "healthy";

      return {
        id: campaign.id,
        name: campaign.name,
        status: campaign.status,
        sent: campaign.messages_sent,
        total: campaign.total_contacts,
        deliveryRate,
        responseRate,
        failureRate,
        health,
      };
    })
    .sort((a, b) => b.failureRate - a.failureRate || b.sent - a.sent)
    .slice(0, 6);
}

function buildOfferPerformance(offers: Offer[], campaigns: Campaign[]): PerformanceRow[] {
  const campaignTotals = campaigns.reduce(
    (totals, campaign) => ({
      audience: totals.audience + campaign.total_contacts,
      responses: totals.responses + campaign.replies_received,
      qualified: totals.qualified + campaign.contacts_qualified,
      optOuts: totals.optOuts + campaign.contacts_opted_out,
    }),
    { audience: 0, responses: 0, qualified: 0, optOuts: 0 },
  );

  return offers
    .filter((offer) => offer.is_active || (offer.opt_ins ?? 0) > 0 || (offer.page_views ?? 0) > 0)
    .map((offer) => {
      const audience = offer.page_views ?? campaignTotals.audience;
      const responses = offer.opt_ins ?? campaignTotals.responses;
      const qualified = Math.max(offer.opt_ins ?? 0, Math.round(responses * 0.35));

      return {
        id: offer.id,
        name: offer.name,
        audience,
        responses,
        qualified,
        optOuts: campaignTotals.optOuts,
        conversionRate: percentage(responses, audience),
        source: "offer" as const,
      };
    })
    .sort((a, b) => b.conversionRate - a.conversionRate || b.responses - a.responses)
    .slice(0, 5);
}

function buildSegmentPerformance(segments: Segment[], campaigns: Campaign[]): PerformanceRow[] {
  const replies = campaigns.reduce((total, campaign) => total + campaign.replies_received, 0);
  const qualified = campaigns.reduce((total, campaign) => total + campaign.contacts_qualified, 0);
  const optOuts = campaigns.reduce((total, campaign) => total + campaign.contacts_opted_out, 0);
  const totalContacts = segments.reduce((total, segment) => total + segment.contact_count, 0);

  return segments
    .map((segment) => {
      const share = totalContacts > 0 ? segment.contact_count / totalContacts : 0;
      const segmentReplies = Math.round(replies * share);
      const segmentQualified = Math.round(qualified * share);

      return {
        id: segment.id,
        name: segment.name,
        audience: segment.contact_count,
        responses: segmentReplies,
        qualified: segmentQualified,
        optOuts: Math.round(optOuts * share),
        conversionRate: percentage(segmentQualified, segment.contact_count),
        source: "segment" as const,
      };
    })
    .sort((a, b) => b.conversionRate - a.conversionRate || b.audience - a.audience)
    .slice(0, 5);
}

function buildAnglePerformance(campaigns: Campaign[]): PerformanceRow[] {
  return campaigns
    .filter((campaign) => campaign.messages_sent > 0 || campaign.total_contacts > 0)
    .map((campaign) => ({
      id: campaign.id,
      name: campaign.name,
      audience: campaign.total_contacts,
      responses: campaign.replies_received,
      qualified: campaign.contacts_qualified,
      optOuts: campaign.contacts_opted_out,
      conversionRate: percentage(campaign.contacts_qualified, campaign.messages_sent),
      source: "angle" as const,
    }))
    .sort((a, b) => b.conversionRate - a.conversionRate || b.responses - a.responses)
    .slice(0, 5);
}

function buildAiResponderPerformance(campaigns: Campaign[]): AgentStat[] {
  const byAgent = new Map<string, AgentStat>();

  campaigns.forEach((campaign) => {
    if (!campaign.agent_id || !campaign.ai_enabled) return;

    const current = byAgent.get(campaign.agent_id) ?? {
      id: campaign.agent_id,
      name: `Agent ${byAgent.size + 1}`,
      calls: 0,
      messages: 0,
      success_rate: 0,
    };

    current.messages += campaign.messages_sent;
    current.calls += campaign.campaign_type.includes("voice") ? campaign.messages_sent : 0;
    current.success_rate = percentage(
      current.success_rate + campaign.contacts_qualified,
      Math.max(current.messages, 1),
    );
    byAgent.set(campaign.agent_id, current);
  });

  return Array.from(byAgent.values()).sort((a, b) => b.success_rate - a.success_rate).slice(0, 5);
}

export const outboundGrowthAnalyticsApi = {
  get: async (workspaceId: string): Promise<OutboundGrowthAnalyticsResponse> => {
    const [campaignsData, offersData, segmentsData, pendingActionsData, contactsData] = await Promise.all([
      campaignsApi.list(workspaceId, { page_size: MAX_ITEMS }),
      offersApi.list(workspaceId, { page_size: MAX_ITEMS }),
      segmentsApi.list(workspaceId, { page_size: MAX_ITEMS }),
      pendingActionsApi.list(workspaceId, { page_size: 10, status: "pending" }),
      contactsApi.list(workspaceId, {
        page_size: 8,
        status: "qualified",
        sort_by: "last_conversation",
      }),
    ]);

    const campaigns = campaignsData.items;
    const offers = offersData.items;
    const segments = segmentsData.items;
    const pendingActions = pendingActionsData.items;
    const warmContacts = contactsData.items;
    const campaignHealth = buildCampaignHealth(campaigns);
    const totalSent = campaigns.reduce((total, campaign) => total + campaign.messages_sent, 0);
    const totalOptOuts = campaigns.reduce((total, campaign) => total + campaign.contacts_opted_out, 0);

    return {
      offerPerformance: buildOfferPerformance(offers, campaigns),
      segmentPerformance: buildSegmentPerformance(segments, campaigns),
      anglePerformance: buildAnglePerformance(campaigns),
      warmLeadActions: pendingActions.map((action) => ({
        id: action.id,
        description: action.description,
        urgency: action.urgency,
        actionType: action.action_type,
        createdAt: action.created_at,
        contactName: actionContactName(action),
      })),
      campaignHealth,
      optOuts: {
        total: totalOptOuts,
        rate: percentage(totalOptOuts, totalSent),
        byCampaign: campaigns
          .filter((campaign) => campaign.contacts_opted_out > 0)
          .map((campaign) => ({
            id: campaign.id,
            name: campaign.name,
            optOuts: campaign.contacts_opted_out,
            rate: percentage(campaign.contacts_opted_out, campaign.messages_sent),
          }))
          .sort((a, b) => b.optOuts - a.optOuts)
          .slice(0, 5),
      },
      aiResponderPerformance: buildAiResponderPerformance(campaigns),
      totals: {
        campaigns: campaigns.length,
        activeCampaigns: campaigns.filter((campaign) => campaign.status === "running").length,
        warmLeads: pendingActionsData.total + warmContacts.length,
        qualified: campaigns.reduce((total, campaign) => total + campaign.contacts_qualified, 0),
        replies: campaigns.reduce((total, campaign) => total + campaign.replies_received, 0),
      },
    };
  },
};
