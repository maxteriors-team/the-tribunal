"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { offersApi } from "@/lib/api/offers";
import { workspacesApi } from "@/lib/api/workspaces";
import { queryKeys } from "@/lib/query-keys";

const AUTOPILOT_SETTINGS_KEY = "outbound_autopilot";

interface AutopilotSettings {
  enabled: boolean;
  offer_id: string | null;
}

function readAutopilot(settings: Record<string, unknown> | undefined): AutopilotSettings {
  const raw = settings?.[AUTOPILOT_SETTINGS_KEY];
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { enabled: false, offer_id: null };
  }
  const record = raw as Record<string, unknown>;
  return {
    enabled: record.enabled === true,
    offer_id: typeof record.offer_id === "string" ? record.offer_id : null,
  };
}

export function OutboundAutopilotCard({ workspaceId }: { workspaceId: string }) {
  const queryClient = useQueryClient();

  const { data: workspace, isPending: workspacePending } = useQuery({
    queryKey: queryKeys.workspaces.detail(workspaceId),
    queryFn: () => workspacesApi.get(workspaceId),
  });

  const { data: offersData } = useQuery({
    queryKey: queryKeys.offers.all(workspaceId),
    queryFn: () => offersApi.list(workspaceId),
  });

  const autopilot = readAutopilot(workspace?.settings);
  const activeOffers = (offersData?.items ?? []).filter((o) => o.is_active);

  const mutation = useMutation({
    mutationFn: (next: AutopilotSettings) =>
      workspacesApi.update(workspaceId, {
        settings: {
          ...(workspace?.settings ?? {}),
          [AUTOPILOT_SETTINGS_KEY]: next,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.workspaces.detail(workspaceId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.dashboard.todayQueue(workspaceId),
      });
    },
  });

  const handleToggle = (enabled: boolean) => {
    // Enabling with exactly one active offer: preselect it so autopilot can
    // actually draft instead of immediately nudging about a missing offer.
    const offerId =
      autopilot.offer_id ??
      (enabled && activeOffers.length === 1 ? activeOffers[0].id : null);
    mutation.mutate({ enabled, offer_id: offerId });
  };

  const handleOfferChange = (offerId: string) => {
    mutation.mutate({ enabled: autopilot.enabled, offer_id: offerId });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-4">
          <div>
            <CardTitle>Outbound Autopilot</CardTitle>
            <CardDescription>
              Every morning, draft an outreach campaign from fresh ad-library
              contacts and park it for your approval. Nothing sends without
              you.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {mutation.isPending && (
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            )}
            <Switch
              checked={autopilot.enabled}
              disabled={workspacePending || mutation.isPending}
              onCheckedChange={handleToggle}
              aria-label="Toggle outbound autopilot"
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <Label>Default offer for drafted campaigns</Label>
        <Select
          value={autopilot.offer_id ?? ""}
          onValueChange={handleOfferChange}
          disabled={workspacePending || mutation.isPending || activeOffers.length === 0}
        >
          <SelectTrigger className="max-w-md">
            <SelectValue
              placeholder={
                activeOffers.length === 0
                  ? "No active offers — create one first"
                  : "Select an offer"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {activeOffers.map((offer) => (
              <SelectItem key={offer.id} value={offer.id}>
                {offer.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {autopilot.enabled && !autopilot.offer_id && (
          <p className="text-xs text-amber-600">
            Autopilot is on but has no offer — morning drafts will be skipped
            until you pick one.
          </p>
        )}
        {mutation.isError && (
          <p className="text-xs text-destructive">
            Couldn&apos;t save autopilot settings. Please try again.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
