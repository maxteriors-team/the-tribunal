"use client";

import { Search } from "lucide-react";

import { ContactFilterBuilder } from "@/components/filters/contact-filter-builder";
import { Input } from "@/components/ui/input";
import type { ContactListResponse } from "@/lib/api/contacts";
import { contactStatusLabels } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import type { ContactStatus, FilterDefinition } from "@/types";

const STATUS_ORDER: (ContactStatus | "all")[] = [
  "all",
  "new",
  "contacted",
  "qualified",
  "converted",
  "lost",
];

interface StatusSegmentedControlProps {
  selectedStatus: ContactStatus | null;
  onStatusChange: (status: ContactStatus | null) => void;
  counts: ContactListResponse["status_counts"] | undefined;
}

function StatusSegmentedControl({
  selectedStatus,
  onStatusChange,
  counts,
}: StatusSegmentedControlProps) {
  return (
    <div
      role="group"
      aria-label="Contact status: counts across all matching contacts, before selecting a status"
      className="bg-muted/40 inline-flex flex-wrap items-center gap-1 rounded-lg border p-1"
    >
      {STATUS_ORDER.map((status) => {
        const isActive = status === "all" ? !selectedStatus : selectedStatus === status;
        return (
          <button
            key={status}
            type="button"
            aria-pressed={isActive}
            aria-label={`${status === "all" ? "All" : contactStatusLabels[status]} ${counts?.[status] ?? "count unavailable"}`}
            onClick={() => onStatusChange(status === "all" ? null : status)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              isActive
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {status === "all" ? "All" : contactStatusLabels[status]}
            <span className="ml-1 tabular-nums opacity-60">{counts?.[status] ?? "—"}</span>
          </button>
        );
      })}
    </div>
  );
}

export interface ContactsFilterBarProps {
  inputValue: string;
  onInputChange: (value: string) => void;
  statusFilter: string | null;
  onStatusChange: (status: ContactStatus | null) => void;
  statusCounts: ContactListResponse["status_counts"] | undefined;
  workspaceId: string | null;
  filters: FilterDefinition | null;
  onFiltersChange: (filters: FilterDefinition | null) => void;
}

export function ContactsFilterBar({
  inputValue,
  onInputChange,
  statusFilter,
  onStatusChange,
  statusCounts,
  workspaceId,
  filters,
  onFiltersChange,
}: ContactsFilterBarProps) {
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      {/* Left: status segmented control + advanced filter trigger/chips */}
      <div className="flex flex-wrap items-start gap-2">
        <StatusSegmentedControl
          selectedStatus={statusFilter as ContactStatus | null}
          onStatusChange={onStatusChange}
          counts={statusCounts}
        />
        {workspaceId && (
          <ContactFilterBuilder
            compact
            workspaceId={workspaceId}
            filters={filters}
            onFiltersChange={onFiltersChange}
          />
        )}
      </div>

      {/* Right: search */}
      <div className="relative w-full lg:max-w-xs">
        <Search className="text-muted-foreground absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" />
        <Input
          placeholder="Search contacts…"
          value={inputValue}
          onChange={(e) => onInputChange(e.target.value)}
          className="pl-9"
        />
      </div>
    </div>
  );
}
