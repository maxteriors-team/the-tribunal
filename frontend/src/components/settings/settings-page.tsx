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

export const settingsGroups = [
  { value: "personal", label: "Personal" },
  { value: "crm", label: "CRM" },
  { value: "automation", label: "Automation" },
  { value: "integrations", label: "Integrations" },
  { value: "workspace", label: "Workspace" },
] as const;

export type SettingsGroup = (typeof settingsGroups)[number]["value"];

export interface SettingsTab {
  value: string;
  label: string;
  icon: LucideIcon;
  group: SettingsGroup;
  requires?: Capability;
}

export const settingsTabs: SettingsTab[] = [
  { value: "profile", label: "Profile", icon: User, group: "personal" },
  { value: "notifications", label: "Notifications", icon: Bell, group: "personal" },
  { value: "calendar", label: "My Calendar", icon: CalendarDays, group: "personal" },
  { value: "tags", label: "Tags", icon: Tags, group: "crm", requires: "crm:write" },
  { value: "reviews", label: "Reviews", icon: Star, group: "crm", requires: "workspace:manage" },
  {
    value: "proposals",
    label: "Proposals",
    icon: FileText,
    group: "crm",
    requires: "billing:write",
  },
  { value: "pricing", label: "Pricing", icon: DollarSign, group: "crm", requires: "billing:write" },
  {
    value: "sales-targets",
    label: "Sales Targets",
    icon: Target,
    group: "crm",
    requires: "workspace:manage",
  },
  {
    value: "locations",
    label: "Locations",
    icon: MapPin,
    group: "crm",
    requires: "locations:manage",
  },
  {
    value: "lead-sources",
    label: "Lead Sources",
    icon: FileInput,
    group: "crm",
    requires: "crm:write",
  },
  {
    value: "nudges",
    label: "Nudges",
    icon: HandHeart,
    group: "automation",
    requires: "workspace:manage",
  },
  {
    value: "attach-rules",
    label: "Attach Rules",
    icon: Layers,
    group: "automation",
    requires: "billing:write",
  },
  {
    value: "pipeline",
    label: "Pipeline",
    icon: KanbanSquare,
    group: "automation",
    requires: "pipeline:write",
  },
  {
    value: "speed-to-lead",
    label: "Speed to Lead",
    icon: Zap,
    group: "automation",
    requires: "outreach:write",
  },
  {
    value: "estimate-followup",
    label: "Estimate Follow-up",
    icon: CalendarClock,
    group: "automation",
    requires: "outreach:write",
  },
  {
    value: "quote-revival",
    label: "Quote Revival",
    icon: History,
    group: "automation",
    requires: "outreach:write",
  },
  {
    value: "neighbors",
    label: "Neighbors",
    icon: Home,
    group: "automation",
    requires: "outreach:write",
  },
  {
    value: "integrations",
    label: "Integrations",
    icon: Webhook,
    group: "integrations",
    requires: "workspace:manage",
  },
  {
    value: "billing",
    label: "Billing",
    icon: CreditCard,
    group: "workspace",
    requires: "billing:read",
  },
  { value: "team", label: "Team", icon: Building2, group: "workspace", requires: "members:manage" },
];

export function canSeeSettingsTab(
  tab: SettingsTab,
  can: (capability: Capability) => boolean,
): boolean {
  return !tab.requires || can(tab.requires);
}

export function groupSettingsTabs(tabs: SettingsTab[]) {
  return settingsGroups
    .map((group) => ({
      ...group,
      tabs: tabs.filter((tab) => tab.group === group.value),
    }))
    .filter((group) => group.tabs.length > 0);
}

interface SettingsTabNavigationProps {
  activeTab: string;
  groups: ReturnType<typeof groupSettingsTabs>;
}

export function SettingsTabNavigation({ activeTab, groups }: SettingsTabNavigationProps) {
  return (
    <HorizontalScroll
      activeKey={activeTab}
      aria-label="Settings sections, scroll horizontally"
      data-testid="settings-tabs-scroll"
      viewportClassName="md:overflow-visible"
    >
      <TabsList
        aria-label="Settings sections"
        className="grid h-auto w-max min-w-full grid-flow-col items-start justify-start gap-5 rounded-none bg-transparent p-0 md:w-full md:grid-flow-row md:grid-cols-2 xl:grid-cols-5"
      >
        {groups.map((group) => (
          <div
            key={group.value}
            role="presentation"
            data-settings-group={group.value}
            className="min-w-52 space-y-2 border-l pl-4 first:border-l-0 first:pl-0 md:min-w-0 md:first:border-l md:first:pl-4"
          >
            <div
              id={`settings-group-${group.value}`}
              data-settings-group-label
              className="px-1 text-xs font-semibold text-muted-foreground"
            >
              {group.label}
            </div>
            <div role="presentation" className="flex flex-wrap gap-1">
              {group.tabs.map((tab) => (
                <TabsTrigger
                  key={tab.value}
                  value={tab.value}
                  aria-label={tab.label}
                  aria-describedby={`settings-group-${group.value}`}
                  className="min-h-9 shrink-0 gap-2 px-3 py-2"
                >
                  <tab.icon className="size-4" aria-hidden="true" />
                  <span>{tab.label}</span>
                </TabsTrigger>
              ))}
            </div>
          </div>
        ))}
      </TabsList>
    </HorizontalScroll>
  );
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
  const visibleSettingsGroups = groupSettingsTabs(visibleSettingsTabs);
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
        <SettingsTabNavigation activeTab={defaultTab} groups={visibleSettingsGroups} />

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
