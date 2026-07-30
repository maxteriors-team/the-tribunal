"use client";

import { Download, Loader2, MapPin, Printer, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCapabilities } from "@/hooks/useCapabilities";
import {
  useGenerateNeighbors,
  useJobNeighbors,
  useUpdateNeighborEntry,
} from "@/hooks/useJobNeighbors";
import { jobsApi, type NeighborEntry, type NeighborStatus } from "@/lib/api/jobs";
import { getApiErrorMessage, getApiErrorStatus } from "@/lib/utils/errors";

interface JobNeighborsPanelProps {
  workspaceId: string;
  jobId: string;
  /** Read-only view for workers on their own calendar (no generate/export). */
  readOnly?: boolean;
}

const STATUS_OPTIONS: { value: NeighborStatus; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "contacted", label: "Contacted" },
  { value: "skipped", label: "Skipped" },
  { value: "converted", label: "Converted" },
];

const statusColors: Record<NeighborStatus, string> = {
  pending: "border-slate-300 text-slate-600",
  contacted: "border-sky-300 text-sky-700",
  skipped: "border-amber-300 text-amber-700",
  converted: "border-emerald-300 text-emerald-700",
};

/** Human labels for the persisted `messaging_blocked_reason` vocabulary. */
const BLOCKED_LABELS: Record<string, string> = {
  no_contact: "No contact record — print only",
  missing_sms_consent: "No messaging consent — print only",
  global_opt_out: "Opted out — print only",
  no_phone_number: "No phone number — print only",
  no_email_address: "No email address — print only",
  messaging_disabled: "Messaging off for this workspace",
};

function metersLabel(meters: number): string {
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
}

/** Escape one CSV field: quote it and double any embedded quotes. */
function csvCell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '""';
  return `"${String(value).replace(/"/g, '""')}"`;
}

/**
 * Neighbor outreach for a finished job: the houses that watched the crew work.
 *
 * The panel is print-first on purpose. Every row shows a distance and a status an
 * operator can advance as they walk the street, and the export produces a
 * door-hanger / direct-mail list. Rows that cannot legally be messaged say so
 * inline rather than offering an action the server would refuse.
 */
export function JobNeighborsPanel({
  workspaceId,
  jobId,
  readOnly = false,
}: JobNeighborsPanelProps) {
  // Mirror the server: generate, export, and status changes are all dispatcher
  // writes (`jobs:write`). Without this a technician would be shown an "Export
  // list" button that only ever returns a 403 — and the export is a page of
  // neighbours' home addresses, so it is not a button to offer speculatively.
  const { can } = useCapabilities();
  const canWrite = !readOnly && can("jobs:write");
  const neighbors = useJobNeighbors(workspaceId, jobId);
  const generate = useGenerateNeighbors(workspaceId, jobId);
  const updateEntry = useUpdateNeighborEntry(workspaceId, jobId);
  const [exporting, setExporting] = useState(false);

  // A 404 is the "not generated yet" state, not a failure.
  const notGenerated = getApiErrorStatus(neighbors.error) === 404;

  const handleGenerate = () => {
    generate.mutate(
      {},
      {
        onSuccess: (batch) =>
          toast.success(
            batch.total === 0
              ? "No neighbors found in range"
              : `${batch.total} neighbor${batch.total === 1 ? "" : "s"} on this street`,
          ),
        onError: (err) =>
          toast.error(getApiErrorMessage(err, "Failed to find neighbors")),
      },
    );
  };

  const handleStatus = (entry: NeighborEntry, status: NeighborStatus) => {
    if (status === entry.status) return;
    updateEntry.mutate(
      { entryId: entry.id, body: { status } },
      { onError: (err) => toast.error(getApiErrorMessage(err, "Failed to update neighbor")) },
    );
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const data = await jobsApi.neighborsExport(workspaceId, jobId);
      const header = [
        "name",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "country",
        "distance_meters",
        "status",
        "channel",
      ];
      const csv = [
        header.map(csvCell).join(","),
        ...(data.rows ?? []).map((row) =>
          [
            csvCell(row.customer_name ?? row.label),
            csvCell(row.address_line1),
            csvCell(row.address_line2),
            csvCell(row.city),
            csvCell(row.state),
            csvCell(row.postal_code),
            csvCell(row.country),
            csvCell(Math.round(row.distance_meters)),
            csvCell(row.status),
            csvCell(row.channel),
          ].join(","),
        ),
      ].join("\n");

      // Built and downloaded in the browser: the list is customer PII, so it
      // never gets written to a shareable server path.
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `neighbors-${jobId}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      toast.success(`Exported ${data.total} neighbor${data.total === 1 ? "" : "s"}`);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Failed to export neighbors"));
    } finally {
      setExporting(false);
    }
  };

  if (neighbors.isPending) {
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (neighbors.isError && !notGenerated) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        Failed to load neighbors. Please try again.
      </p>
    );
  }

  const entries = neighbors.data?.entries ?? [];

  if (notGenerated || entries.length === 0) {
    return (
      <div className="space-y-3 py-6 text-center">
        <MapPin className="mx-auto size-6 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">
            {notGenerated ? "No neighbor list yet" : "No neighbors in range"}
          </p>
          <p className="text-sm text-muted-foreground">
            {notGenerated
              ? "The houses that watched this crew work are the warmest leads you have."
              : "Nothing else is mapped inside the search radius. Widen it in Settings → Neighbors."}
          </p>
        </div>
        {canWrite && (
          <Button size="sm" onClick={handleGenerate} disabled={generate.isPending}>
            {generate.isPending ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 size-4" />
            )}
            Find neighbors
          </Button>
        )}
      </div>
    );
  }

  const batch = neighbors.data;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {entries.length} within {metersLabel(batch?.radius_meters ?? 0)} ·{" "}
          {batch?.pending_count ?? 0} to work
        </p>
        {canWrite && (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={handleGenerate}
              disabled={generate.isPending}
            >
              {generate.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
              Refresh
            </Button>
            <Button size="sm" onClick={() => void handleExport()} disabled={exporting}>
              {exporting ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <Download className="mr-2 size-4" />
              )}
              Export list
            </Button>
          </div>
        )}
      </div>

      <ul className="divide-y rounded-md border text-sm">
        {entries.map((entry) => (
          <li key={entry.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium">
                  {entry.customer_name ?? entry.label ?? "Neighbor"}
                </span>
                <Badge variant="outline" className={statusColors[entry.status]}>
                  {metersLabel(entry.distance_meters)}
                </Badge>
              </div>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                {entry.messageable ? (
                  <>Can be messaged · {entry.channel}</>
                ) : (
                  <>
                    <Printer className="size-3" />
                    {BLOCKED_LABELS[entry.messaging_blocked_reason ?? ""] ??
                      "Print only"}
                  </>
                )}
              </div>
            </div>
            <Select
              value={entry.status}
              onValueChange={(value) => handleStatus(entry, value as NeighborStatus)}
              disabled={!canWrite || updateEntry.isPending}
            >
              <SelectTrigger
                className="h-8 w-32"
                aria-label={`Status for ${entry.customer_name ?? entry.label ?? "neighbor"}`}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </li>
        ))}
      </ul>
    </div>
  );
}
