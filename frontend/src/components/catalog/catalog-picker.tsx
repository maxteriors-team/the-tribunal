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
}

/**
 * "Add from price book" dropdown. Lists the workspace's active catalog items and
 * hands the chosen one back so a line-item editor can autofill name + price.
 */
export function CatalogPicker({ onPick, disabled }: CatalogPickerProps) {
  const workspaceId = useWorkspaceId();

  const query = useQuery({
    queryKey: queryKeys.catalogItems.list(workspaceId ?? ""),
    queryFn: () => catalogApi.list(workspaceId ?? "", { page_size: 200 }),
    enabled: Boolean(workspaceId),
  });

  const items = query.data?.items ?? [];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm" disabled={disabled}>
          <BookMarked className="mr-1.5 h-3.5 w-3.5" />
          Add from price book
          <ChevronDown className="ml-1 h-3.5 w-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-72 w-72 overflow-y-auto">
        <DropdownMenuLabel>Price book</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 ? (
          <DropdownMenuItem disabled>
            {query.isLoading ? "Loading…" : "No items yet"}
          </DropdownMenuItem>
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
