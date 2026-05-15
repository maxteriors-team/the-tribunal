"use client";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface LeadFilterState {
  hasPhone: boolean;
  /** Show only results that have a website (opt-in, used by AI page). */
  hasWebsite?: boolean;
  /** Show only results that have NO website (opt-in, used by basic find/scrape). */
  noWebsite?: boolean;
  /** Hide toll-free numbers (800/888/etc). */
  hideTollFree?: boolean;
  /** Minimum rating threshold, or null for any. */
  minRating: number | null;
}

interface LeadFiltersProps {
  filters: LeadFilterState;
  onFiltersChange: (filters: LeadFilterState) => void;
  /** Total filtered results count (post-filter). */
  filteredCount: number;
  /** Total raw results count (pre-filter). */
  totalCount: number;
  /** Render the "Has phone" filter checkbox. Default true. */
  showHasPhone?: boolean;
  /** Render the "Has website" filter checkbox (AI page). */
  showHasWebsite?: boolean;
  /** Render the "No website" filter checkbox. */
  showNoWebsite?: boolean;
  /** Render the "Hide 800 numbers" filter checkbox. */
  showHideTollFree?: boolean;
  /** Tag the "Has website" label with an "AI" badge. */
  websiteBadge?: boolean;
}

export function LeadFilters({
  filters,
  onFiltersChange,
  filteredCount,
  totalCount,
  showHasPhone = true,
  showHasWebsite = false,
  showNoWebsite = false,
  showHideTollFree = false,
  websiteBadge = false,
}: LeadFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-4 p-3 bg-muted/50 rounded-lg">
      {showHasPhone && (
        <div className="flex items-center gap-2">
          <Checkbox
            id="filter-phone"
            checked={filters.hasPhone}
            onCheckedChange={(checked) =>
              onFiltersChange({ ...filters, hasPhone: checked === true })
            }
          />
          <Label htmlFor="filter-phone" className="text-sm cursor-pointer">
            Has phone
          </Label>
        </div>
      )}
      {showHasWebsite && (
        <div className="flex items-center gap-2">
          <Checkbox
            id="filter-has-website"
            checked={filters.hasWebsite ?? false}
            onCheckedChange={(checked) =>
              onFiltersChange({ ...filters, hasWebsite: checked === true })
            }
          />
          <Label
            htmlFor="filter-has-website"
            className="text-sm cursor-pointer flex items-center gap-1"
          >
            Has website
            {websiteBadge && (
              <Badge variant="secondary" className="text-[10px] px-1 py-0">
                AI
              </Badge>
            )}
          </Label>
        </div>
      )}
      {showNoWebsite && (
        <div className="flex items-center gap-2">
          <Checkbox
            id="filter-no-website"
            checked={filters.noWebsite ?? false}
            onCheckedChange={(checked) =>
              onFiltersChange({ ...filters, noWebsite: checked === true })
            }
          />
          <Label htmlFor="filter-no-website" className="text-sm cursor-pointer">
            No website
          </Label>
        </div>
      )}
      {showHideTollFree && (
        <div className="flex items-center gap-2">
          <Checkbox
            id="filter-toll-free"
            checked={filters.hideTollFree ?? false}
            onCheckedChange={(checked) =>
              onFiltersChange({ ...filters, hideTollFree: checked === true })
            }
          />
          <Label htmlFor="filter-toll-free" className="text-sm cursor-pointer">
            Hide 800 numbers
          </Label>
        </div>
      )}
      <div className="flex items-center gap-2">
        <Label className="text-sm">Min rating:</Label>
        <Select
          value={filters.minRating?.toString() || "any"}
          onValueChange={(v) =>
            onFiltersChange({
              ...filters,
              minRating: v === "any" ? null : parseFloat(v),
            })
          }
        >
          <SelectTrigger className="w-20 h-8">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Any</SelectItem>
            <SelectItem value="3">3+</SelectItem>
            <SelectItem value="4">4+</SelectItem>
            <SelectItem value="4.5">4.5+</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="flex-1" />
      <span className="text-sm text-muted-foreground">
        {filteredCount} of {totalCount} shown
      </span>
    </div>
  );
}

const TOLL_FREE_PREFIXES = ["800", "888", "877", "866", "855", "844", "833"];

export function isTollFreeNumber(phone: string | null): boolean {
  if (!phone) return false;
  const digits = phone.replace(/\D/g, "");
  // Strip leading country code "1" for US numbers
  const normalized =
    digits.startsWith("1") && digits.length === 11 ? digits.slice(1) : digits;
  return TOLL_FREE_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

/**
 * Apply the standard lead filter set to a result list. Each filter is opt-in
 * via the LeadFilterState shape — undefined/false skips that filter.
 */
export function applyLeadFilters<
  T extends {
    has_phone: boolean;
    has_website: boolean;
    phone_number: string | null;
    rating: number | null;
  },
>(results: T[], filters: LeadFilterState): T[] {
  return results.filter((r) => {
    if (filters.hasPhone && !r.has_phone) return false;
    if (filters.hasWebsite && !r.has_website) return false;
    if (filters.noWebsite && r.has_website) return false;
    if (filters.hideTollFree && isTollFreeNumber(r.phone_number)) return false;
    if (filters.minRating && (!r.rating || r.rating < filters.minRating))
      return false;
    return true;
  });
}
