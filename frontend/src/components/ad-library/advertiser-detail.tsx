"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  adLibraryQueryOptions,
  type AdCreative,
} from "@/lib/api/ad-library";

interface AdvertiserDetailProps {
  workspaceId: string;
  advertiserId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPromote?: (advertiserId: string) => void;
  isPromoting?: boolean;
}

export function AdvertiserDetail({
  workspaceId,
  advertiserId,
  open,
  onOpenChange,
  onPromote,
  isPromoting = false,
}: AdvertiserDetailProps) {
  const detailQuery = useQuery({
    ...adLibraryQueryOptions.advertiser(workspaceId, advertiserId ?? ""),
    enabled: open && Boolean(workspaceId) && Boolean(advertiserId),
  });
  const advertiser = detailQuery.data;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>
            {advertiser?.advertiser_name ?? "Advertiser"}
          </SheetTitle>
          <SheetDescription>
            {advertiser?.website_host ?? advertiser?.advertiser_key ?? ""}
          </SheetDescription>
        </SheetHeader>

        {detailQuery.isLoading ? (
          <p className="p-4 text-sm text-muted-foreground">Loading…</p>
        ) : !advertiser ? (
          <p className="p-4 text-sm text-muted-foreground">Not found.</p>
        ) : (
          <div className="space-y-6 p-4">
            <SignalSummary
              score={advertiser.opportunity_score}
              reasons={advertiser.reasons}
            />

            <MetricGrid
              metrics={[
                {
                  label: "Longest run",
                  value: `${advertiser.longest_running_active_days}d`,
                },
                {
                  label: "Distinct creatives",
                  value: String(advertiser.distinct_creative_count),
                },
                {
                  label: "Refresh / 30d",
                  value: advertiser.creative_refresh_rate.toFixed(1),
                },
                {
                  label: "Continuity",
                  value: `${Math.round(advertiser.continuity_score * 100)}%`,
                },
                {
                  label: "Active ads",
                  value: String(advertiser.active_ad_count),
                },
                {
                  label: "Media mix",
                  value:
                    Object.entries(advertiser.media_mix)
                      .map(([k, v]) => `${k} ${v}`)
                      .join(", ") || "—",
                },
              ]}
            />

            {advertiser.traced_contact ? (
              <TracedContact contact={advertiser.traced_contact} />
            ) : null}

            <CreativeGallery creatives={advertiser.creatives} />
          </div>
        )}

        <SheetFooter>
          {advertiser && onPromote ? (
            <Button
              disabled={isPromoting}
              onClick={() => onPromote(advertiser.id)}
            >
              Add to CRM / Start outreach
            </Button>
          ) : null}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function SignalSummary({
  score,
  reasons,
}: {
  score: number;
  reasons: string[];
}) {
  return (
    <div className="space-y-2 rounded-md border p-4">
      <div className="flex items-center gap-2">
        <Badge variant={score >= 75 ? "default" : "secondary"}>
          Opportunity {score}
        </Badge>
      </div>
      {reasons.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function MetricGrid({
  metrics,
}: {
  metrics: { label: string; value: string }[];
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {metrics.map((metric) => (
        <div key={metric.label} className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">{metric.label}</p>
          <p className="text-sm font-medium">{metric.value}</p>
        </div>
      ))}
    </div>
  );
}

function TracedContact({
  contact,
}: {
  contact: Record<string, unknown>;
}) {
  const website = typeof contact.website_url === "string" ? contact.website_url : null;
  const linkedin = typeof contact.linkedin_url === "string" ? contact.linkedin_url : null;
  return (
    <div className="space-y-1 rounded-md border p-4">
      <p className="text-sm font-medium">Traced contact</p>
      <div className="flex flex-wrap gap-2 text-xs">
        {contact.has_email ? <Badge variant="outline">Email found</Badge> : null}
        {contact.has_phone ? <Badge variant="outline">Phone found</Badge> : null}
        {website ? (
          <a
            href={website}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-primary"
          >
            Website <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
        {linkedin ? (
          <a
            href={linkedin}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-primary"
          >
            LinkedIn <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
      </div>
    </div>
  );
}

function CreativeGallery({ creatives }: { creatives: AdCreative[] }) {
  if (creatives.length === 0) {
    return null;
  }
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">Ads ({creatives.length})</p>
      <div className="space-y-3">
        {creatives.map((creative) => (
          <div key={creative.id} className="space-y-1 rounded-md border p-3">
            <div className="flex items-center justify-between gap-2">
              <Badge variant={creative.is_active ? "default" : "outline"}>
                {creative.is_active ? "Active" : "Stopped"}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {creative.media_type}
              </span>
            </div>
            {creative.body ? (
              <p className="text-sm">{creative.body}</p>
            ) : creative.title ? (
              <p className="text-sm">{creative.title}</p>
            ) : null}
            {creative.snapshot_url ? (
              <a
                href={creative.snapshot_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-primary"
              >
                View ad <ExternalLink className="h-3 w-3" />
              </a>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
