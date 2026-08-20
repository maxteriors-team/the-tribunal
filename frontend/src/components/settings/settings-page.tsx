"use client";

import {
  Bell,
  Building2,
  CalendarClock,
  CalendarDays,
  CreditCard,
  DollarSign,
  FileInput,
  FileText,
  HandHeart,
  History,
  Home,
  KanbanSquare,
  Layers,
  MapPin,
  Star,
  Tags,
  Target,
  User,
  Webhook,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useSyncExternalStore } from "react";

import { AttachRulesSettingsTab } from "@/components/settings/attach-rules-settings-tab";
import { BillingSettingsTab } from "@/components/settings/billing-settings-tab";
import { FinancingSettingsCard } from "@/components/settings/financing-settings-card";
import { IntegrationsSettingsTab } from "@/components/settings/integrations-settings-tab";
import { LeadSourcesSettingsTab } from "@/components/settings/lead-sources-settings-tab";
import { LocationsSettingsTab } from "@/components/settings/locations-settings-tab";
import { NeighborOutreachSettingsTab } from "@/components/settings/neighbor-outreach-settings-tab";
import { NotificationsSettingsTab } from "@/components/settings/notifications-settings-tab";
import { NudgeSettingsTab } from "@/components/settings/nudge-settings-tab";
import { PermanentPricingSettingsCard } from "@/components/settings/permanent-pricing-settings-card";
import { PipelineSettingsTab } from "@/components/settings/pipeline-settings-tab";
import { ProfileSettingsTab } from "@/components/settings/profile-settings-tab";
import { ProposalSettingsTab } from "@/components/settings/proposal-settings-tab";
import { QuoteFollowupSettingsTab } from "@/components/settings/quote-followup-settings-tab";
import { QuoteRevivalSettingsTab } from "@/components/settings/quote-revival-settings-tab";
import { ReviewSettingsTab } from "@/components/settings/review-settings-tab";
import { SalesTargetsSettingsTab } from "@/components/settings/sales-targets-settings-tab";
import { SeasonalPricingSettingsTab } from "@/components/settings/seasonal-pricing-settings-tab";
import { SpeedToLeadSettingsTab } from "@/components/settings/speed-to-lead-settings-tab";
import { TeamSettingsTab } from "@/components/settings/team-settings-tab";
import { UpsellRanksSettingsCard } from "@/components/settings/upsell-ranks-settings-card";
import { TagManagement } from "@/components/tags/tag-management";
import { HorizontalScroll } from "@/components/ui/horizontal-scroll";
import { PageLoadingState } from "@/components/ui/page-state";
import { QueryErrorBoundary } from "@/components/ui/query-error-boundary";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCapabilities } from "@/hooks/useCapabilities";
import type { Capability } from "@/lib/permissions";

export interface SettingsTab {
  value: string;
  label: string;
  icon: LucideIcon;
  requires?: Capability;
}

export const settingsTabs: SettingsTab[] = [
  { value: "profile", label: "Profile", icon: User },
  { value: "tags", label: "Tags", icon: Tags, requires: "crm:write" },
  { value: "notifications", label: "Notifications", icon: Bell },
  { value: "nudges", label: "Nudges", icon: HandHeart, requires: "workspace:manage" },
  { value: "reviews", label: "Reviews", icon: Star, requires: "workspace:manage" },
  { value: "proposals", label: "Proposals", icon: FileText, requires: "billing:write" },
  { value: "pricing", label: "Pricing", icon: DollarSign, requires: "billing:write" },
  { value: "attach-rules", label: "Attach Rules", icon: Layers, requires: "billing:write" },
  { value: "sales-targets", label: "Sales Targets", icon: Target, requires: "workspace:manage" },
  { value: "pipeline", label: "Pipeline", icon: KanbanSquare, requires: "pipeline:write" },
  { value: "speed-to-lead", label: "Speed to Lead", icon: Zap, requires: "outreach:write" },
  {
    value: "estimate-followup",
    label: "Estimate Follow-up",
    icon: CalendarClock,
    requires: "outreach:write",
  },
  { value: "quote-revival", label: "Quote Revival", icon: History, requires: "outreach:write" },
  { value: "neighbors", label: "Neighbors", icon: Home, requires: "outreach:write" },
  { value: "calendar", label: "My Calendar", icon: CalendarDays },
  {
    value: "integrations",
    label: "Integrations",
    icon: Webhook,
    requires: "workspace:manage",
  },
  { value: "billing", label: "Billing", icon: CreditCard, requires: "billing:read" },
  { value: "team", label: "Team", icon: Building2, requires: "members:manage" },
  { value: "locations", label: "Locations", icon: MapPin, requires: "locations:manage" },
  { value: "lead-sources", label: "Lead Sources", icon: FileInput, requires: "crm:write" },
];

export function canSeeSettingsTab(
  tab: SettingsTab,
  can: (capability: Capability) => boolean,
): boolean {
  return !tab.requires || can(tab.requires);
}

const subscribeToHydration = () => () => undefined;

function useIsHydrated(): boolean {
  return useSyncExternalStore(
    subscribeToHydration,
    () => true,
    () => false,
  );
}

export function SettingsPage() {
  const searchParams = useSearchParams();
  const isHydrated = useIsHydrated();
  const { can } = useCapabilities();
  const visibleSettingsTabs = settingsTabs.filter((tab) => canSeeSettingsTab(tab, can));
  const requestedTab = searchParams.get("tab");
  const defaultTab = visibleSettingsTabs.some((tab) => tab.value === requestedTab)
    ? requestedTab!
    : "profile";

  if (!isHydrated) {
    return <PageLoadingState className="min-h-[24rem]" message="Loading settings…" />;
  }

  return (
    <div className="space-y-6 p-4 sm:p-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Manage your account and application preferences</p>
      </div>

      <Tabs key={defaultTab} defaultValue={defaultTab} className="space-y-6">
        <HorizontalScroll
          activeKey={defaultTab}
          aria-label="Settings sections, scroll horizontally"
          data-testid="settings-tabs-scroll"
        >
          <TabsList
            aria-label="Settings sections"
            className="h-auto w-max min-w-full justify-start gap-1 sm:w-full sm:flex-wrap"
          >
            {visibleSettingsTabs.map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                aria-label={tab.label}
                className="shrink-0 gap-2 px-3"
              >
                <tab.icon className="size-4" aria-hidden="true" />
                <span>{tab.label}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </HorizontalScroll>

        <TabsContent value="profile">
          <QueryErrorBoundary message="Failed to load profile settings. Please try again.">
            <ProfileSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="tags">
          <QueryErrorBoundary message="Failed to load tags. Please try again.">
            <TagManagement />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="notifications">
          <QueryErrorBoundary message="Failed to load notification settings. Please try again.">
            <NotificationsSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="nudges">
          <QueryErrorBoundary message="Failed to load nudge settings. Please try again.">
            <NudgeSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="reviews">
          <QueryErrorBoundary message="Failed to load review settings. Please try again.">
            <ReviewSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="proposals">
          <QueryErrorBoundary message="Failed to load proposal settings. Please try again.">
            <ProposalSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="pricing">
          <QueryErrorBoundary message="Failed to load pricing settings. Please try again.">
            <div className="space-y-6">
              <FinancingSettingsCard />
              <UpsellRanksSettingsCard />
              <PermanentPricingSettingsCard />
              <SeasonalPricingSettingsTab />
            </div>
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="attach-rules">
          <QueryErrorBoundary message="Failed to load attach rules. Please try again.">
            <AttachRulesSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="sales-targets">
          <QueryErrorBoundary message="Failed to load sales targets. Please try again.">
            <SalesTargetsSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="pipeline">
          <QueryErrorBoundary message="Failed to load pipeline settings. Please try again.">
            <PipelineSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="speed-to-lead">
          <QueryErrorBoundary message="Failed to load speed-to-lead settings. Please try again.">
            <SpeedToLeadSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="estimate-followup">
          <QueryErrorBoundary message="Failed to load estimate follow-up settings. Please try again.">
            <QuoteFollowupSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="quote-revival">
          <QueryErrorBoundary message="Failed to load quote revival settings. Please try again.">
            <QuoteRevivalSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="neighbors">
          <QueryErrorBoundary message="Failed to load neighbor outreach settings. Please try again.">
            <NeighborOutreachSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="calendar">
          <QueryErrorBoundary message="Failed to load your calendar connection. Please try again.">
            <IntegrationsSettingsTab calendarOnly />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="integrations">
          <QueryErrorBoundary message="Failed to load integrations. Please try again.">
            <IntegrationsSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="billing">
          <QueryErrorBoundary message="Failed to load billing settings. Please try again.">
            <BillingSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="team">
          <QueryErrorBoundary message="Failed to load team settings. Please try again.">
            <TeamSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="locations">
          <QueryErrorBoundary message="Failed to load locations. Please try again.">
            <LocationsSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>

        <TabsContent value="lead-sources">
          <QueryErrorBoundary message="Failed to load lead sources. Please try again.">
            <LeadSourcesSettingsTab />
          </QueryErrorBoundary>
        </TabsContent>
      </Tabs>
    </div>
  );
}
