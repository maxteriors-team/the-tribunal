"use client";

import { CheckCircle2, Clock, Megaphone, Sparkles, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Status pill for enrichment workflow progress (used on contact cards).
 */
export function EnrichmentStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;

  const statusConfig = {
    pending: { icon: Clock, label: "Enriching...", className: "text-warning bg-warning/10" },
    enriched: { icon: CheckCircle2, label: "Enriched", className: "text-success bg-success/10" },
    failed: { icon: XCircle, label: "Failed", className: "text-destructive bg-destructive/10" },
    skipped: { icon: null, label: "No website", className: "text-muted-foreground bg-muted" },
  };

  const config = statusConfig[status as keyof typeof statusConfig];
  if (!config) return null;

  const Icon = config.icon;

  return (
    <Badge variant="outline" className={cn("gap-1 text-xs", config.className)}>
      {Icon && <Icon className="h-3 w-3" />}
      {config.label}
    </Badge>
  );
}

/**
 * Color-coded numeric lead-score badge.
 */
export function LeadScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;

  const color =
    score >= 80
      ? "text-success bg-success/10 border-success/20"
      : score >= 40
        ? "text-warning bg-warning/10 border-warning/20"
        : "text-muted-foreground bg-muted border-border";

  return (
    <Badge variant="outline" className={cn("gap-1 text-xs font-semibold", color)}>
      <Sparkles className="h-3 w-3" />
      {score}
    </Badge>
  );
}

/**
 * Renders one badge per active ad pixel (Meta, Google).
 */
export function AdPixelBadges({
  adPixels,
}: {
  adPixels?: { meta_pixel?: boolean; google_ads?: boolean };
}) {
  if (!adPixels) return null;
  const badges: { label: string; active: boolean }[] = [
    { label: "Meta Ads", active: !!adPixels.meta_pixel },
    { label: "Google Ads", active: !!adPixels.google_ads },
  ];
  const activeBadges = badges.filter((b) => b.active);
  if (activeBadges.length === 0) return null;

  return (
    <>
      {activeBadges.map((badge) => (
        <Badge
          key={badge.label}
          variant="outline"
          className="text-xs text-primary bg-primary/10 border-primary/20 gap-1"
        >
          <Megaphone className="h-3 w-3" />
          {badge.label}
        </Badge>
      ))}
    </>
  );
}
