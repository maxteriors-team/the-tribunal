"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { LeadSourcePicker } from "@/components/lead-sources/source-pickers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageErrorState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  leadSourcesApi,
  type UnattributedLead,
} from "@/lib/api/lead-sources";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

function leadName(lead: UnattributedLead): string {
  return [lead.first_name, lead.last_name].filter(Boolean).join(" ").trim();
}

function QueueRow({
  workspaceId,
  lead,
}: {
  workspaceId: string;
  lead: UnattributedLead;
}) {
  const queryClient = useQueryClient();
  const [sourceId, setSourceId] = useState<string | undefined>(
    lead.suggested_lead_source_id ?? undefined,
  );

  const assignMutation = useMutation({
    mutationFn: () =>
      leadSourcesApi.assignSource(workspaceId, lead.contact_id, {
        lead_source_id: sourceId!,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.leadSources.unattributed(workspaceId),
      });
      toast.success(`Source assigned to ${leadName(lead) || "lead"}`);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to assign source")),
  });

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 space-y-1">
        <div className="flex items-center gap-2">
          <span className="font-medium">{leadName(lead) || "Unnamed lead"}</span>
          <Badge variant="outline" className="text-xs">
            {lead.source ?? "Unknown"}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          {lead.phone_number ?? lead.email ?? "No contact details"}
        </p>
      </div>

      <div className="flex items-center gap-2">
        <div className="w-48">
          <LeadSourcePicker
            workspaceId={workspaceId}
            value={sourceId}
            onChange={setSourceId}
            placeholder="Assign source"
            aria-label={`Assign source for ${leadName(lead) || "lead"}`}
          />
        </div>
        <Button
          size="sm"
          disabled={!sourceId || assignMutation.isPending}
          onClick={() => assignMutation.mutate()}
        >
          {assignMutation.isPending && (
            <Loader2 className="mr-2 size-4 animate-spin" />
          )}
          Assign
        </Button>
      </div>
    </div>
  );
}

interface UnknownAttributionQueueProps {
  workspaceId: string;
}

/**
 * Cleanup queue for leads captured without a known source. Operators assign a
 * lead source so the lead can be attributed in ROI reporting.
 */
export function UnknownAttributionQueue({
  workspaceId,
}: UnknownAttributionQueueProps) {
  const {
    data: leads,
    isPending,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.leadSources.unattributed(workspaceId),
    queryFn: () => leadSourcesApi.listUnattributed(workspaceId),
    enabled: !!workspaceId,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Unknown source cleanup</CardTitle>
        <CardDescription>
          Assign a lead source to leads captured without attribution so they
          count toward channel ROI.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : error ? (
          <PageErrorState
            message={(error as Error).message || "Failed to load the queue"}
            onRetry={() => refetch()}
          />
        ) : !leads?.length ? (
          <div className="flex flex-col items-center py-10 text-center text-muted-foreground">
            <CheckCircle2 className="mb-3 size-10 text-success/70" />
            <p className="font-medium">All leads attributed</p>
            <p className="text-sm">
              Nothing to clean up — every lead has a known source.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {leads.length} lead{leads.length === 1 ? "" : "s"} need a source
            </p>
            {leads.map((lead) => (
              <QueueRow
                key={lead.contact_id}
                workspaceId={workspaceId}
                lead={lead}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
