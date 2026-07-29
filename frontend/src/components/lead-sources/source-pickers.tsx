"use client";

import { useQuery } from "@tanstack/react-query";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  leadSourcesApi,
  type LeadSource,
  type LeadSourceType,
} from "@/lib/api/lead-sources";
import { queryKeys } from "@/lib/query-keys";

/**
 * Channel options used to rank lead-source ROI, in dashboard display order.
 * The first four are the always-ranked acquisition channels, then the
 * word-of-mouth and physical channels, then the `other` catch-all bucket.
 *
 * Mirrors `LeadSourceType` / `SOURCE_TYPE_LABELS` in
 * `backend/app/services/dashboard/lead_source_roi_service.py`.
 */
export const SOURCE_TYPE_OPTIONS: ReadonlyArray<{
  value: LeadSourceType;
  label: string;
}> = [
  { value: "facebook_ads", label: "Facebook Ads" },
  { value: "google_ads", label: "Google Ads" },
  { value: "organic", label: "Organic" },
  { value: "phone_radio", label: "Phone / Radio" },
  { value: "referral_partner", label: "Referral Partner" },
  { value: "repeat_customer", label: "Repeat Customer" },
  { value: "truck_wrap", label: "Truck Wrap" },
  { value: "yard_sign", label: "Yard Sign" },
  { value: "canvass_neighbor", label: "Jobsite Canvass" },
  { value: "other", label: "Other" },
];

// Keyed lookup for `sourceTypeLabel`. Typed as a partial record so a channel
// added to `LeadSourceType` without an option here degrades to the raw value
// instead of silently type-asserting a missing label as present.
const SOURCE_TYPE_LABELS: Partial<Record<LeadSourceType, string>> =
  Object.fromEntries(SOURCE_TYPE_OPTIONS.map((o) => [o.value, o.label]));

export function sourceTypeLabel(type: LeadSourceType): string {
  return SOURCE_TYPE_LABELS[type] ?? type;
}

// ---------------------------------------------------------------------------
// SourceTypePicker — pick the top-level acquisition channel.
// ---------------------------------------------------------------------------

export function SourceTypePicker({
  value,
  onChange,
  id,
  includeOther = true,
  disabled,
  "aria-label": ariaLabel = "Channel",
}: {
  value: LeadSourceType | undefined;
  onChange: (value: LeadSourceType) => void;
  id?: string;
  includeOther?: boolean;
  disabled?: boolean;
  "aria-label"?: string;
}) {
  const options = includeOther
    ? SOURCE_TYPE_OPTIONS
    : SOURCE_TYPE_OPTIONS.filter((o) => o.value !== "other");

  return (
    <Select
      value={value ?? ""}
      onValueChange={(v) => onChange(v as LeadSourceType)}
      disabled={disabled}
    >
      <SelectTrigger id={id} aria-label={ariaLabel} className="w-full">
        <SelectValue placeholder="Select a channel" />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// ---------------------------------------------------------------------------
// LeadSourcePicker — pick a configured lead source (optionally filtered by
// channel). Loads sources for the workspace.
// ---------------------------------------------------------------------------

export function LeadSourcePicker({
  workspaceId,
  value,
  onChange,
  onClear,
  allowClear = false,
  sourceType,
  id,
  placeholder = "Select a lead source",
  "aria-label": ariaLabel = "Lead source",
}: {
  workspaceId: string;
  value: string | undefined;
  onChange: (leadSourceId: string, source: LeadSource) => void;
  onClear?: () => void;
  allowClear?: boolean;
  /** When set, only sources matching this channel are listed. */
  sourceType?: LeadSourceType;
  id?: string;
  placeholder?: string;
  "aria-label"?: string;
}) {
  const { data: sources, isPending } = useQuery({
    queryKey: queryKeys.leadSources.all(workspaceId),
    queryFn: () => leadSourcesApi.list(workspaceId),
    enabled: !!workspaceId,
  });

  const options = (sources ?? []).filter(
    (s) => !sourceType || s.source_type === sourceType,
  );

  const emptyLabel = isPending
    ? "Loading sources…"
    : sourceType
      ? "No matching sources"
      : "No sources yet";

  return (
    <Select
      value={value ?? (allowClear ? "__none__" : "")}
      onValueChange={(v) => {
        if (v === "__none__") {
          onClear?.();
          return;
        }
        const picked = options.find((s) => s.id === v);
        if (picked) onChange(v, picked);
      }}
      disabled={isPending || (options.length === 0 && !allowClear)}
    >
      <SelectTrigger id={id} aria-label={ariaLabel} className="w-full">
        <SelectValue
          placeholder={options.length === 0 ? emptyLabel : placeholder}
        />
      </SelectTrigger>
      <SelectContent>
        {allowClear && (
          <SelectItem value="__none__">No lead source</SelectItem>
        )}
        {options.map((source) => (
          <SelectItem key={source.id} value={source.id}>
            {source.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// ---------------------------------------------------------------------------
// CampaignPicker — pick an attribution campaign under a lead source.
// ---------------------------------------------------------------------------

export function CampaignPicker({
  workspaceId,
  leadSourceId,
  value,
  onChange,
  onClear,
  allowClear = false,
  id,
  "aria-label": ariaLabel = "Campaign",
}: {
  workspaceId: string;
  leadSourceId: string | undefined;
  value: string | undefined;
  onChange: (campaignId: string) => void;
  onClear?: () => void;
  allowClear?: boolean;
  id?: string;
  "aria-label"?: string;
}) {
  const { data: campaigns, isPending } = useQuery({
    queryKey: queryKeys.leadSources.campaigns(workspaceId, leadSourceId ?? ""),
    queryFn: () => leadSourcesApi.listCampaigns(workspaceId, leadSourceId!),
    enabled: !!workspaceId && !!leadSourceId,
  });

  const options = campaigns ?? [];
  const disabled =
    !leadSourceId || isPending || (options.length === 0 && !allowClear);

  const placeholder = !leadSourceId
    ? "Pick a source first"
    : isPending
      ? "Loading campaigns…"
      : options.length === 0
        ? "No campaigns"
        : "All campaigns";

  return (
    <Select
      value={value ?? (allowClear ? "__none__" : "")}
      onValueChange={(v) => {
        if (v === "__none__") {
          onClear?.();
          return;
        }
        onChange(v);
      }}
      disabled={disabled}
    >
      <SelectTrigger id={id} aria-label={ariaLabel} className="w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {allowClear && <SelectItem value="__none__">No campaign</SelectItem>}
        {options.map((campaign) => (
          <SelectItem key={campaign.id} value={campaign.id}>
            {campaign.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
