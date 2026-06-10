"use client";

import { CheckCircle2, CircleDashed } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AdAdvertiser } from "@/lib/api/ad-library";

interface AdvertiserTableProps {
  advertisers: AdAdvertiser[];
  onSelect: (advertiser: AdAdvertiser) => void;
  selectedIds?: ReadonlySet<string>;
  onToggleSelect?: (advertiserId: string) => void;
}

function scoreVariant(score: number): "default" | "secondary" | "outline" {
  if (score >= 75) return "default";
  if (score >= 50) return "secondary";
  return "outline";
}

export function AdvertiserTable({
  advertisers,
  onSelect,
  selectedIds,
  onToggleSelect,
}: AdvertiserTableProps) {
  const selectable = Boolean(onToggleSelect);

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {selectable ? <TableHead className="w-8" /> : null}
            <TableHead>Advertiser</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead className="text-right">Longest run</TableHead>
            <TableHead className="text-right">Creatives</TableHead>
            <TableHead className="text-right">Refresh / 30d</TableHead>
            <TableHead className="text-right">Continuity</TableHead>
            <TableHead className="text-center">Contact</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {advertisers.map((advertiser) => (
            <TableRow
              key={advertiser.id}
              className="cursor-pointer"
              onClick={() => onSelect(advertiser)}
            >
              {selectable ? (
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    aria-label={`Select ${advertiser.advertiser_name ?? "advertiser"}`}
                    checked={selectedIds?.has(advertiser.id) ?? false}
                    onChange={() => onToggleSelect?.(advertiser.id)}
                  />
                </TableCell>
              ) : null}
              <TableCell>
                <div className="font-medium">
                  {advertiser.advertiser_name ?? advertiser.advertiser_key}
                </div>
                {advertiser.website_host ? (
                  <div className="text-xs text-muted-foreground">
                    {advertiser.website_host}
                  </div>
                ) : null}
              </TableCell>
              <TableCell className="text-right">
                <Badge variant={scoreVariant(advertiser.opportunity_score)}>
                  {advertiser.opportunity_score}
                </Badge>
              </TableCell>
              <TableCell className="text-right">
                {advertiser.longest_running_active_days}d
              </TableCell>
              <TableCell className="text-right">
                {advertiser.distinct_creative_count}
              </TableCell>
              <TableCell className="text-right">
                {advertiser.creative_refresh_rate.toFixed(1)}
              </TableCell>
              <TableCell className="text-right">
                {Math.round(advertiser.continuity_score * 100)}%
              </TableCell>
              <TableCell className="text-center">
                {advertiser.contact_traced ? (
                  <CheckCircle2 className="mx-auto h-4 w-4 text-emerald-500" />
                ) : (
                  <CircleDashed className="mx-auto h-4 w-4 text-muted-foreground" />
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

interface AdvertiserTableToolbarProps {
  total: number;
  selectedCount: number;
  onlyQualified: boolean;
  onToggleQualified: (value: boolean) => void;
  onBulkPromote?: () => void;
  isPromoting?: boolean;
}

export function AdvertiserTableToolbar({
  total,
  selectedCount,
  onlyQualified,
  onToggleQualified,
  onBulkPromote,
  isPromoting = false,
}: AdvertiserTableToolbarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>{total} advertisers</span>
        <Button
          size="sm"
          variant={onlyQualified ? "default" : "outline"}
          onClick={() => onToggleQualified(!onlyQualified)}
        >
          {onlyQualified ? "ICP only" : "Show all"}
        </Button>
      </div>
      {onBulkPromote ? (
        <Button
          size="sm"
          disabled={selectedCount === 0 || isPromoting}
          onClick={onBulkPromote}
        >
          Add {selectedCount > 0 ? selectedCount : ""} to CRM
        </Button>
      ) : null}
    </div>
  );
}
