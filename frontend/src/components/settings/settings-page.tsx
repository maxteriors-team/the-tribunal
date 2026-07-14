"use client";

import { Bell, Building2, CalendarClock, CreditCard, DollarSign, FileInput, FileText, HandHeart, History, Home, Layers, MapPin, Star, Tags, Target, User, Webhook, Zap } from "lucide-react";
import { useSearchParams } from "next/navigation";

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
import { ProfileSettingsTab } from "@/components/settings/profile-settings-tab";
import { ProposalSettingsTab } from "@/components/settings/proposal-settings-tab";
import { QuoteFollowupSettingsTab } from "@/components/settings/quote-followup-settings-tab";
import { QuoteRevivalSettingsTab } from "@/components/settings/quote-revival-settings-tab";
import { ReviewSettingsTab } from "@/components/settings/review-settings-tab";
import { SalesTargetsSettingsTab } from "@/components/settings/sales-targets-settings-tab";
import { SeasonalPricingSettingsTab } from "@/components/settings/seasonal-pricing-settings-tab";
import { SpeedToLeadSettingsTab } from "@/components/settings/speed-to-lead-settings-tab";
import { TeamSettingsTab } from "@/components/settings/team-settings-tab";
import { TagManagement } from "@/components/tags/tag-management";
import { QueryErrorBoundary } from "@/components/ui/query-error-boundary";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const settingsTabs = [
  { value: "profile", label: "Profile", icon: User },
  { value: "tags", label: "Tags", icon: Tags },
  { value: "notifications", label: "Notifications", icon: Bell },
  { value: "nudges", label: "Nudges", icon: HandHeart },
  { value: "reviews", label: "Reviews", icon: Star },
  { value: "proposals", label: "Proposals", icon: FileText },
  { value: "pricing", label: "Pricing", icon: DollarSign },
  { value: "attach-rules", label: "Attach Rules", icon: Layers },
  { value: "sales-targets", label: "Sales Targets", icon: Target },
  { value: "speed-to-lead", label: "Speed to Lead", icon: Zap },
  { value: "estimate-followup", label: "Estimate Follow-up", icon: CalendarClock },
  { value: "quote-revival", label: "Quote Revival", icon: History },
  { value: "neighbors", label: "Neighbors", icon: Home },
  { value: "integrations", label: "Integrations", icon: Webhook },
  { value: "billing", label: "Billing", icon: CreditCard },
  { value: "team", label: "Team", icon: Building2 },
  { value: "locations", label: "Locations", icon: MapPin },
  { value: "lead-sources", label: "Lead Sources", icon: FileInput },
];

const TAB_VALUES = new Set(settingsTabs.map((tab) => tab.value));

export function SettingsPage() {
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const defaultTab =
    requestedTab && TAB_VALUES.has(requestedTab) ? requestedTab : "profile";

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Manage your account and application preferences
        </p>
      </div>

      <Tabs defaultValue={defaultTab} className="space-y-6">
        {/*
          Tabs size to their own labels and wrap onto extra rows as needed.
          Do NOT use a fixed `grid-cols-N` here: equal `minmax(0, 1fr)` tracks
          are narrower than labels like "Notifications" / "Speed to Lead", and
          because the triggers are `whitespace-nowrap` the text overflows its
          cell and collides with the neighbouring tab's icon.
        */}
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1">
          {settingsTabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value} className="flex-none gap-2">
              <tab.icon className="size-4" />
              <span className="hidden sm:inline">{tab.label}</span>
            </TabsTrigger>
          ))}
        </TabsList>

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
