"use client";

import { X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

export interface ResourceListBulkBarProps {
  /** Number of currently selected rows. */
  selectedCount: number;
  /** Singular resource noun, e.g. "contact". Pluralized automatically. */
  resourceName: string;
  /** True when every visible row is selected (header checkbox = checked). */
  allVisibleSelected: boolean;
  /** True when some but not all visible rows are selected (header = indeterminate). */
  someVisibleSelected: boolean;
  /** Toggle selection of all visible rows. */
  onToggleAllVisible: () => void;
  /** Clear the entire selection. */
  onClearSelection: () => void;
  /** Bulk action controls (buttons, dropdowns) rendered on the right. */
  children?: ReactNode;
  /** Optional banner row rendered beneath the bar (e.g. "select all matching"). */
  banner?: ReactNode;
  className?: string;
}

/**
 * Standardized bulk-action toolbar for selectable lists/tables.
 *
 * Renders a tri-state "select all visible" checkbox, the selection count, a
 * clear button, and a slot for per-feature bulk actions. Pair with
 * {@link useRowSelection} for the selection state.
 */
export function ResourceListBulkBar({
  selectedCount,
  resourceName,
  allVisibleSelected,
  someVisibleSelected,
  onToggleAllVisible,
  onClearSelection,
  children,
  banner,
  className,
}: ResourceListBulkBarProps) {
  const checkboxState = allVisibleSelected
    ? true
    : someVisibleSelected
      ? "indeterminate"
      : false;

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 p-3">
        <Checkbox
          checked={checkboxState}
          onCheckedChange={onToggleAllVisible}
          aria-label={`Select all visible ${resourceName}s`}
        />
        <span className="text-sm font-medium">
          {selectedCount === 0
            ? `Select ${resourceName}s`
            : `${selectedCount} selected`}
        </span>
        <div className="flex-1" />
        {selectedCount > 0 && (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={onClearSelection}
              className="gap-1.5 text-muted-foreground"
            >
              <X className="h-3.5 w-3.5" />
              Clear
            </Button>
            {children ? <div className="h-4 w-px bg-border" /> : null}
            {children}
          </>
        )}
      </div>
      {banner}
    </div>
  );
}
