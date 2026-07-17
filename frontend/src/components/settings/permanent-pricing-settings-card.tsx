"use client";

/**
 * Settings → Pricing: the Permanent Holiday Lighting editor (operator self-serve).
 *
 * Permanent LED roofline is priced per linear foot plus a controller/hub that
 * carries a number of channels. This card lets a non-technical operator switch
 * the offering on and tune every rate — the per-linear-foot rate is the headline
 * knob the rep sees in the roofline estimator. Saving PUTs the whole `permanent`
 * block back (the endpoint replaces blocks wholesale), so `perks` and every
 * other pricing field round-trip untouched. No developer or deploy needed.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { PermanentConfig } from "@/types/sales-wizard";

// Editable working copy. Numbers are held as strings so a half-typed value never
// snaps to 0 mid-edit; they're parsed and validated on save.
interface DraftFields {
  enabled: boolean;
  label: string;
  perFt: string;
  controllerBase: string;
  perChannel: string;
  includedChannels: string;
  minimum: string;
}

function toDraft(cfg: PermanentConfig): DraftFields {
  return {
    enabled: cfg.enabled,
    label: cfg.label ?? "Permanent Holiday Lighting",
    perFt: String(cfg.per_ft ?? 0),
    controllerBase: String(cfg.controller_base ?? 0),
    perChannel: String(cfg.per_channel ?? 0),
    includedChannels: String(cfg.included_channels ?? 0),
    minimum: String(cfg.minimum ?? 0),
  };
}

export function PermanentPricingSettingsCard() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: pricing, isPending } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(workspaceId!),
    enabled: !!workspaceId,
    // Shared with the seasonal editor by key (React Query dedupes the fetch).
    // Keep it stable so a background refetch can't wipe unsaved edits — this card
    // writes the cache directly on save.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const [draft, setDraft] = useState<DraftFields | null>(null);
  // Snapshot of the server block so save preserves `perks` (and any future field
  // this editor doesn't expose). Same identity-guard pattern as the seasonal tab.
  const [serverPermanent, setServerPermanent] = useState<PermanentConfig | null>(
    null,
  );

  if (pricing?.permanent && pricing.permanent !== serverPermanent) {
    setServerPermanent(pricing.permanent);
    setDraft(toDraft(pricing.permanent));
  }

  const mutation = useMutation({
    mutationFn: (permanent: PermanentConfig) =>
      salesWizardApi.updatePricing(workspaceId!, { permanent }),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        queryKeys.salesWizard.pricing(workspaceId ?? ""),
        updated,
      );
      toast.success("Permanent lighting pricing saved");
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save permanent pricing")),
  });

  const disabled = mutation.isPending || !serverPermanent || !draft;

  const patch = (p: Partial<DraftFields>) =>
    setDraft((prev) => (prev ? { ...prev, ...p } : prev));

  const save = () => {
    if (!serverPermanent || !draft) return;

    const perFt = Number.parseFloat(draft.perFt);
    const controllerBase = Number.parseFloat(draft.controllerBase);
    const perChannel = Number.parseFloat(draft.perChannel);
    const includedChannels = Number.parseInt(draft.includedChannels, 10);
    const minimum = Number.parseFloat(draft.minimum);
    const label = draft.label.trim();

    const numeric: Array<[string, number]> = [
      ["Per-foot rate", perFt],
      ["Controller base price", controllerBase],
      ["Per-channel rate", perChannel],
      ["Included channels", includedChannels],
      ["Job minimum", minimum],
    ];
    for (const [name, value] of numeric) {
      if (!Number.isFinite(value) || value < 0) {
        toast.error(`${name} must be a number ≥ 0`);
        return;
      }
    }
    if (!label) {
      toast.error("Give the offering a name");
      return;
    }

    // Spread the server snapshot first so unexposed fields (perks) survive the
    // block-replace save; then apply the edited values.
    mutation.mutate({
      ...serverPermanent,
      enabled: draft.enabled,
      label,
      per_ft: perFt,
      controller_base: controllerBase,
      per_channel: perChannel,
      included_channels: includedChannels,
      minimum,
    });
  };

  if (isPending || !draft) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>Permanent Holiday Lighting</CardTitle>
            <CardDescription>
              Year-round LED roofline priced per linear foot plus a controller.
              Turn it on to offer it in the roofline estimator and the
              permanent-vs-seasonal comparison.
            </CardDescription>
          </div>
          <Switch
            checked={draft.enabled}
            onCheckedChange={(v) => patch({ enabled: v })}
            disabled={disabled}
            aria-label="Offer permanent holiday lighting"
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2 max-w-xs">
          <Label htmlFor="perm-per-ft">Price per linear foot ($)</Label>
          <Input
            id="perm-per-ft"
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            value={draft.perFt}
            onChange={(e) => patch({ perFt: e.target.value })}
            disabled={disabled}
          />
          <p className="text-xs text-muted-foreground">
            The headline rate for the permanent LED roofline run.
          </p>
        </div>

        <Separator />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="perm-controller">Controller base price ($)</Label>
            <Input
              id="perm-controller"
              type="number"
              min={0}
              step="0.01"
              inputMode="decimal"
              value={draft.controllerBase}
              onChange={(e) => patch({ controllerBase: e.target.value })}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              One-time hub that drives the lights.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="perm-minimum">Job minimum ($)</Label>
            <Input
              id="perm-minimum"
              type="number"
              min={0}
              step="0.01"
              inputMode="decimal"
              value={draft.minimum}
              onChange={(e) => patch({ minimum: e.target.value })}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              Floor price for any permanent job. 0 = no minimum.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="perm-per-channel">Price per channel ($)</Label>
            <Input
              id="perm-per-channel"
              type="number"
              min={0}
              step="0.01"
              inputMode="decimal"
              value={draft.perChannel}
              onChange={(e) => patch({ perChannel: e.target.value })}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              Charged for each channel beyond those included.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="perm-included-channels">Included channels</Label>
            <Input
              id="perm-included-channels"
              type="number"
              min={0}
              step="1"
              inputMode="numeric"
              value={draft.includedChannels}
              onChange={(e) => patch({ includedChannels: e.target.value })}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              Channels bundled into the controller base price.
            </p>
          </div>
        </div>

        <div className="space-y-2 max-w-md">
          <Label htmlFor="perm-label">Offering name</Label>
          <Input
            id="perm-label"
            value={draft.label}
            onChange={(e) => patch({ label: e.target.value })}
            disabled={disabled}
          />
          <p className="text-xs text-muted-foreground">
            Shown to customers on the comparison and proposal.
          </p>
        </div>

        <Separator />

        <div className="flex justify-end">
          <Button type="button" onClick={save} disabled={disabled}>
            {mutation.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Saving…
              </>
            ) : (
              "Save permanent pricing"
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
