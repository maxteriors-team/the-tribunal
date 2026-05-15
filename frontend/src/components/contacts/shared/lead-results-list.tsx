"use client";

import { AlertCircle, Globe, MapPin, Phone, Star } from "lucide-react";
import type { ReactNode } from "react";

import type { BusinessResult } from "@/lib/api/scraping";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface LeadResultsListProps {
  results: BusinessResult[];
  selectedIds: Set<string>;
  onToggleSelect: (placeId: string) => void;
  /** "grid" = card grid (find-leads pages). "list" = compact rows (dialog). */
  variant?: "grid" | "list";
  /** Optional badge slot rendered in the card header (e.g. AI enrichment indicator). */
  renderCardBadge?: (result: BusinessResult) => ReactNode;
  /** Max type chips rendered per card. Default 2 for grid, 3 for list. */
  maxTypes?: number;
  /** Wrap the grid in a ScrollArea (used by full-page layouts). Default true. */
  scroll?: boolean;
  emptyMessage?: string;
}

export function LeadResultsList({
  results,
  selectedIds,
  onToggleSelect,
  variant = "grid",
  renderCardBadge,
  maxTypes,
  scroll = true,
  emptyMessage = "No results match your filters",
}: LeadResultsListProps) {
  if (results.length === 0) {
    return (
      <div className="py-16 text-center text-muted-foreground">
        <AlertCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>{emptyMessage}</p>
      </div>
    );
  }

  const body =
    variant === "grid" ? (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 pr-4">
        {results.map((result) => (
          <LeadCardGrid
            key={result.place_id}
            result={result}
            selected={selectedIds.has(result.place_id)}
            onToggle={() => onToggleSelect(result.place_id)}
            renderBadge={renderCardBadge}
            maxTypes={maxTypes ?? 2}
          />
        ))}
      </div>
    ) : (
      <div className="p-2 space-y-2">
        {results.map((result) => (
          <LeadRow
            key={result.place_id}
            result={result}
            selected={selectedIds.has(result.place_id)}
            onToggle={() => onToggleSelect(result.place_id)}
            maxTypes={maxTypes ?? 3}
          />
        ))}
      </div>
    );

  if (!scroll) return body;

  return (
    <ScrollArea
      className={cn(
        variant === "grid" ? "flex-1 min-h-0" : "flex-1 min-h-0 border rounded-lg",
      )}
    >
      {body}
    </ScrollArea>
  );
}

interface LeadCardGridProps {
  result: BusinessResult;
  selected: boolean;
  onToggle: () => void;
  renderBadge?: (result: BusinessResult) => ReactNode;
  maxTypes: number;
}

function LeadCardGrid({ result, selected, onToggle, renderBadge, maxTypes }: LeadCardGridProps) {
  return (
    <Card
      className={cn(
        "cursor-pointer transition-all",
        selected ? "ring-2 ring-primary border-primary" : "hover:border-primary/50",
      )}
      onClick={onToggle}
    >
      <CardHeader className="p-4 pb-2">
        <div className="flex items-start gap-3">
          <Checkbox
            checked={selected}
            onCheckedChange={onToggle}
            className="mt-1"
            onClick={(e) => e.stopPropagation()}
          />
          <div className="flex-1 min-w-0">
            <CardTitle className="text-base truncate">{result.name}</CardTitle>
            {result.rating && (
              <div className="flex items-center gap-1 mt-1">
                <Star className="h-3 w-3 fill-warning text-warning" />
                <span className="text-sm">{result.rating}</span>
                {result.review_count > 0 && (
                  <span className="text-xs text-muted-foreground">
                    ({result.review_count})
                  </span>
                )}
              </div>
            )}
          </div>
          {renderBadge?.(result)}
        </div>
      </CardHeader>
      <CardContent className="p-4 pt-0">
        {result.address && (
          <CardDescription className="flex items-start gap-1 mb-2">
            <MapPin className="h-3 w-3 mt-0.5 shrink-0" />
            <span className="line-clamp-2">{result.address}</span>
          </CardDescription>
        )}
        <div className="flex items-center gap-4 text-sm">
          <div
            className={cn(
              "flex items-center gap-1",
              result.has_phone ? "text-success" : "text-muted-foreground",
            )}
          >
            <Phone className="h-3 w-3" />
            <span className="truncate max-w-[60vw] sm:max-w-[120px]">
              {result.phone_number || "No phone"}
            </span>
          </div>
          <div
            className={cn(
              "flex items-center gap-1",
              result.has_website ? "text-info" : "text-muted-foreground",
            )}
          >
            <Globe className="h-3 w-3" />
            {result.has_website ? "Website" : "None"}
          </div>
        </div>
        {result.types.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {result.types.slice(0, maxTypes).map((type) => (
              <Badge key={type} variant="outline" className="text-xs">
                {type.replace(/_/g, " ")}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface LeadRowProps {
  result: BusinessResult;
  selected: boolean;
  onToggle: () => void;
  maxTypes: number;
}

function LeadRow({ result, selected, onToggle, maxTypes }: LeadRowProps) {
  return (
    <div
      className={cn(
        "p-3 rounded-lg border cursor-pointer transition-colors",
        selected ? "bg-primary/5 border-primary" : "hover:bg-muted/50",
      )}
      onClick={onToggle}
    >
      <div className="flex items-start gap-3">
        <Checkbox checked={selected} onCheckedChange={onToggle} className="mt-1" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium truncate">{result.name}</span>
            {result.rating && (
              <Badge variant="secondary" className="gap-1 shrink-0">
                <Star className="h-3 w-3 fill-warning text-warning" />
                {result.rating}
                {result.review_count > 0 && (
                  <span className="text-muted-foreground">({result.review_count})</span>
                )}
              </Badge>
            )}
          </div>
          {result.address && (
            <div className="flex items-center gap-1 text-sm text-muted-foreground mt-1">
              <MapPin className="h-3 w-3 shrink-0" />
              <span className="truncate">{result.address}</span>
            </div>
          )}
          <div className="flex items-center gap-4 mt-2 text-sm">
            <div
              className={cn(
                "flex items-center gap-1",
                result.has_phone ? "text-success" : "text-muted-foreground",
              )}
            >
              <Phone className="h-3 w-3" />
              {result.phone_number || "No phone"}
            </div>
            <div
              className={cn(
                "flex items-center gap-1",
                result.has_website ? "text-info" : "text-muted-foreground",
              )}
            >
              <Globe className="h-3 w-3" />
              {result.has_website ? "Has website" : "No website"}
            </div>
          </div>
          {result.types.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {result.types.slice(0, maxTypes).map((type) => (
                <Badge key={type} variant="outline" className="text-xs">
                  {type.replace(/_/g, " ")}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
