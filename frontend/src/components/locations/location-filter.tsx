"use client";

import { useQuery } from "@tanstack/react-query";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { businessLocationsApi } from "@/lib/api/locations";
import { queryKeys } from "@/lib/query-keys";

/** Sentinel for "no location filter" — Radix Select disallows an empty value. */
export const ALL_LOCATIONS = "all";

/**
 * Branch (business-location) filter for the jobs board / calendar. Renders
 * nothing until a workspace has at least one active location, so single-branch
 * businesses never see clutter. Emits the selected location id, or `undefined`
 * for "All locations".
 */
export function LocationFilter({
  workspaceId,
  value,
  onChange,
}: {
  workspaceId: string;
  value: string | undefined;
  onChange: (locationId: string | undefined) => void;
}) {
  const { data } = useQuery({
    queryKey: queryKeys.locations.active(workspaceId),
    queryFn: () => businessLocationsApi.list(workspaceId, { is_active: true }),
    enabled: Boolean(workspaceId),
  });

  const locations = data?.items ?? [];
  if (locations.length === 0) return null;

  return (
    <Select
      value={value ?? ALL_LOCATIONS}
      onValueChange={(next) => onChange(next === ALL_LOCATIONS ? undefined : next)}
    >
      <SelectTrigger className="w-[180px]" aria-label="Filter by location">
        <SelectValue placeholder="All locations" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL_LOCATIONS}>All locations</SelectItem>
        {locations.map((location) => (
          <SelectItem key={location.id} value={location.id}>
            {location.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
