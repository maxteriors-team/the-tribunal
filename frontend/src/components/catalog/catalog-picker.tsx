"use client";

import { useQuery } from "@tanstack/react-query";
import { BookMarked, ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { catalogApi } from "@/lib/api/catalog";
import { queryKeys } from "@/lib/query-keys";
import { formatCurrency } from "@/lib/utils/number";
import type { CatalogItem } from "@/types";

interface CatalogPickerProps {
  /** Called with the chosen catalog item so the caller can append a line. */
  onPick: (item: CatalogItem) => void;
  disabled?: boolean;
  /**
   * Show only items in this `service_category`. Used by the attach prompt so
   * "Add gutters" opens straight onto the gutter items instead of the whole
   * price book — the rep is one click from the attach, not one search.
   * Matched case-insensitively because the category is free-form text.
   */
  category?: string;
  /** Overrides the trigger copy, e.g. "Add gutters". */
  label?: string;
  variant?: "outline" | "default" | "secondary";
  /**
   * Trigger classes, so a host with its own scoped theme (the Quote Builder)
   * can render the picker in its own visual language instead of dropping an
   * app-styled control into the middle of it.
   */
  triggerClassName?: string;
}

/**
 * "Add from price book" dropdown. Lists the workspace's active catalog items and
 * hands the chosen one back so a line-item editor can autofill name + price.
 */
export function CatalogPicker({
  onPick,
  disabled,
  category,
  label,
  variant = "outline",
  triggerClassName,
}: CatalogPickerProps) {
  const workspaceId = useWorkspaceId();

  const query = useQuery({
    queryKey: queryKeys.catalogItems.list(workspaceId ?? ""),
    queryFn: () => catalogApi.list(workspaceId ?? "", { page_size: 200 }),
    enabled: Boolean(workspaceId),
  });

  const wanted = category?.trim().toLocaleLowerCase();
  const allItems = query.data?.items ?? [];
  const items = wanted
    ? allItems.filter(
        (item) =>
          (item.service_category ?? "").trim().toLocaleLowerCase() === wanted,
      )
    : allItems;

  let emptyMessage: string;
  if (query.isLoading) {
    emptyMessage = "Loading…";
  } else if (wanted) {
    // A filtered picker with nothing in it is a price-book gap, not a bug, and
    // naming the category is what makes that fixable.
    emptyMessage = `No ${category} items in your price book`;
  } else {
    emptyMessage = "No items yet";
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant={variant}
          size="sm"
          disabled={disabled}
          className={triggerClassName}
        >
          <BookMarked className="mr-1.5 h-3.5 w-3.5" />
          {label ?? "Add from price book"}
          <ChevronDown className="ml-1 h-3.5 w-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-72 w-72 overflow-y-auto">
        <DropdownMenuLabel>{category ?? "Price book"}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 ? (
          <DropdownMenuItem disabled>{emptyMessage}</DropdownMenuItem>
        ) : (
          items.map((item) => (
            <DropdownMenuItem
              key={item.id}
              onSelect={() => onPick(item)}
              className="flex items-center justify-between gap-3"
            >
              <span className="truncate">{item.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {formatCurrency(item.unit_price)}
              </span>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
