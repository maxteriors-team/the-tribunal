"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  phoneNumbersApi,
  type PhoneNumberSearchResult,
  type PhoneNumberUpdateRequest,
} from "@/lib/api/phone-numbers";
import { queryKeys } from "@/lib/query-keys";
import {
  getApiErrorMessage,
  isProviderConfigurationError,
  shouldThrowProviderError,
} from "@/lib/utils/errors";
import type { PhoneNumber } from "@/types";

export interface UsePhoneNumberManagerResult {
  workspaceId: string | null;
  phoneNumbers: PhoneNumber[];
  isLoadingNumbers: boolean;
  numbersError: unknown;
  country: string;
  setCountry: (country: string) => void;
  areaCode: string;
  setAreaCode: (areaCode: string) => void;
  searchResults: PhoneNumberSearchResult[];
  hasSearched: boolean;
  isSearching: boolean;
  isPurchasing: boolean;
  isUpdating: boolean;
  isSyncing: boolean;
  providerNotConfigured: boolean;
  handleSearch: (event: React.FormEvent) => void;
  purchase: (phoneNumber: string) => void;
  updateAttribution: (
    phoneNumberId: string,
    data: PhoneNumberUpdateRequest,
  ) => Promise<PhoneNumber>;
  release: (phoneNumberId: string) => void;
  sync: () => void;
}

/**
 * Container hook for {@link PhoneNumbersTable}: owns the owned-numbers query and
 * the search / purchase / update / release / sync mutations plus form state,
 * so the table itself can stay presentational across its `section`/`page`
 * variants.
 */
export function usePhoneNumberManager(): UsePhoneNumberManagerResult {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const [country, setCountry] = useState("US");
  const [areaCode, setAreaCode] = useState("");
  const [searchResults, setSearchResults] = useState<PhoneNumberSearchResult[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [providerNotConfigured, setProviderNotConfigured] = useState(false);

  const invalidatePhoneNumbers = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.phoneNumbers.all(workspaceId ?? ""),
    });

  const {
    data: phoneNumbersData,
    isPending: isLoadingNumbers,
    error: numbersError,
  } = useQuery({
    queryKey: queryKeys.phoneNumbers.activeOnlyFalse(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.list(workspaceId, { active_only: false });
    },
    enabled: !!workspaceId,
  });

  const searchMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.search(workspaceId, {
        country,
        area_code: areaCode || undefined,
        limit: 10,
      });
    },
    throwOnError: shouldThrowProviderError,
    onMutate: () => setProviderNotConfigured(false),
    onSuccess: (data) => {
      setProviderNotConfigured(false);
      setSearchResults(data);
      setHasSearched(true);
      if (data.length === 0) {
        toast.info("No numbers found matching your criteria");
      }
    },
    onError: (error) => {
      if (isProviderConfigurationError(error)) {
        setProviderNotConfigured(true);
      } else {
        toast.error(getApiErrorMessage(error, "Failed to search for numbers"));
      }
      setSearchResults([]);
      setHasSearched(true);
    },
  });

  const purchaseMutation = useMutation({
    mutationFn: (phoneNumber: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.purchase(workspaceId, {
        phone_number: phoneNumber,
      });
    },
    throwOnError: shouldThrowProviderError,
    onMutate: () => setProviderNotConfigured(false),
    onSuccess: (data) => {
      setProviderNotConfigured(false);
      toast.success(`Successfully purchased ${data.phone_number}`);
      void invalidatePhoneNumbers();
      setSearchResults((prev) => prev.filter((r) => r.phone_number !== data.phone_number));
    },
    onError: (error) => {
      if (isProviderConfigurationError(error)) {
        setProviderNotConfigured(true);
      } else {
        toast.error(getApiErrorMessage(error, "Failed to purchase number"));
      }
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      phoneNumberId,
      data,
    }: {
      phoneNumberId: string;
      data: PhoneNumberUpdateRequest;
    }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.update(workspaceId, phoneNumberId, data);
    },
    onSuccess: () => {
      toast.success("Call tracking attribution saved");
      void invalidatePhoneNumbers();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update phone number");
    },
  });

  const releaseMutation = useMutation({
    mutationFn: (phoneNumberId: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.release(workspaceId, phoneNumberId);
    },
    throwOnError: shouldThrowProviderError,
    onMutate: () => setProviderNotConfigured(false),
    onSuccess: () => {
      setProviderNotConfigured(false);
      toast.success("Phone number released successfully");
      void invalidatePhoneNumbers();
    },
    onError: (error) => {
      if (isProviderConfigurationError(error)) {
        setProviderNotConfigured(true);
      } else {
        toast.error(getApiErrorMessage(error, "Failed to release number"));
      }
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.sync(workspaceId);
    },
    throwOnError: shouldThrowProviderError,
    onMutate: () => setProviderNotConfigured(false),
    onSuccess: (data) => {
      setProviderNotConfigured(false);
      if (data.synced > 0) {
        toast.success(`Synced ${data.synced} phone number(s) from Telnyx`);
      } else {
        toast.info("No new phone numbers to sync");
      }
      void invalidatePhoneNumbers();
    },
    onError: (error) => {
      if (isProviderConfigurationError(error)) {
        setProviderNotConfigured(true);
      } else {
        toast.error(getApiErrorMessage(error, "Failed to sync phone numbers"));
      }
    },
  });

  const phoneNumbers = Array.isArray(phoneNumbersData?.items) ? phoneNumbersData.items : [];

  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault();
    searchMutation.mutate();
  };

  return {
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
    isSearching: searchMutation.isPending,
    isPurchasing: purchaseMutation.isPending,
    isUpdating: updateMutation.isPending,
    isSyncing: syncMutation.isPending,
    providerNotConfigured,
    handleSearch,
    purchase: (phoneNumber) => purchaseMutation.mutate(phoneNumber),
    updateAttribution: (phoneNumberId, data) => updateMutation.mutateAsync({ phoneNumberId, data }),
    release: (phoneNumberId) => releaseMutation.mutate(phoneNumberId),
    sync: () => syncMutation.mutate(),
  };
}
