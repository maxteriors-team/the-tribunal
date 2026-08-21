"use client";

import { Phone, Search } from "lucide-react";

import {
  OwnedNumbersContent,
  SearchNumbersForm,
  SearchResultsContent,
  SyncFromTelnyxButton,
  type PhoneNumbersTableVariant,
} from "@/components/settings/phone-numbers-views";
import { ProviderNotConfiguredBanner } from "@/components/shared/provider-not-configured-banner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { usePhoneNumberManager } from "@/hooks/usePhoneNumberManager";

export type { PhoneNumbersTableVariant };

export interface PhoneNumbersTableProps {
  variant: PhoneNumbersTableVariant;
}

export function PhoneNumbersTable({ variant }: PhoneNumbersTableProps) {
  const {
    workspaceId,
    phoneNumbers,
    isLoadingNumbers,
    numbersError,
    country,
    setCountry,
    areaCode,
    setAreaCode,
    searchResults,
    hasSearched,
    isSearching,
    isPurchasing,
    isUpdating,
    isSyncing,
    providerNotConfigured,
    handleSearch,
    purchase,
    updateAttribution,
    release,
    sync,
  } = usePhoneNumberManager();

  const syncButton = <SyncFromTelnyxButton variant={variant} isSyncing={isSyncing} onSync={sync} />;
  const providerBanner = providerNotConfigured ? (
    <ProviderNotConfiguredBanner
      title="Phone number actions need Telnyx"
      description="Connect Telnyx in Settings, then retry this action."
      restrictedDescription="Ask a workspace owner or admin to connect Telnyx."
      settingsLabel="Set up Telnyx"
    />
  ) : null;

  const ownedNumbersContent = (
    <OwnedNumbersContent
      variant={variant}
      workspaceId={workspaceId ?? ""}
      phoneNumbers={phoneNumbers}
      isLoading={isLoadingNumbers}
      hasError={!!numbersError}
      isUpdating={isUpdating}
      onUpdate={updateAttribution}
      onRelease={release}
    />
  );

  const searchForm = (
    <SearchNumbersForm
      variant={variant}
      country={country}
      onCountryChange={setCountry}
      areaCode={areaCode}
      onAreaCodeChange={setAreaCode}
      isSearching={isSearching}
      onSubmit={handleSearch}
    />
  );

  const searchResultsContent = (
    <SearchResultsContent
      variant={variant}
      hasSearched={hasSearched}
      searchResults={searchResults}
      isPurchasing={isPurchasing}
      onPurchase={purchase}
    />
  );

  if (variant === "section") {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-lg bg-green-500/10">
                <Phone className="size-5 text-green-500" />
              </div>
              <div>
                <CardTitle className="text-base">Phone Numbers</CardTitle>
                <CardDescription>
                  Manage your Telnyx phone numbers for SMS and voice
                </CardDescription>
              </div>
            </div>
            {syncButton}
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {providerBanner}
          <div className="space-y-3">
            <h4 className="text-sm font-medium">Your Phone Numbers</h4>
            {ownedNumbersContent}
          </div>

          <Separator />

          <div className="space-y-4">
            <h4 className="text-sm font-medium">Search for New Numbers</h4>
            {searchForm}
            {searchResultsContent}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Phone Numbers</h1>
          <p className="text-muted-foreground">
            Manage your Telnyx phone numbers for SMS and voice calls
          </p>
        </div>
        {syncButton}
      </div>

      {providerBanner}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Phone className="size-5" />
            Your Phone Numbers
          </CardTitle>
          <CardDescription>Phone numbers currently provisioned in your workspace</CardDescription>
        </CardHeader>
        <CardContent>{ownedNumbersContent}</CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="size-5" />
            Search for New Numbers
          </CardTitle>
          <CardDescription>Find and purchase new phone numbers from Telnyx</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {searchForm}
          {searchResultsContent}
        </CardContent>
      </Card>
    </div>
  );
}
