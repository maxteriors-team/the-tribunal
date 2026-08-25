"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import type { BistroConfig, BistroInstallationConfig } from "@/types/sales-wizard";

interface DraftFields {
  enabled: boolean;
  minimum: string;
  temporaryLights: string;
  temporaryPoles: string;
  permanentLights: string;
  permanentPoles: string;
}

const DEFAULT_TEMPORARY: BistroInstallationConfig = {
  label: "Temporary Bistro Lighting",
  lights_per_ft: 0,
  poles_each: 0,
};
const DEFAULT_PERMANENT: BistroInstallationConfig = {
  label: "Permanent Bistro Lighting",
  lights_per_ft: 0,
  poles_each: 0,
};

function toDraft(config: BistroConfig): DraftFields {
  return {
    enabled: config.enabled,
    minimum: String(config.minimum ?? 0),
    temporaryLights: String(config.temporary?.lights_per_ft ?? 0),
    temporaryPoles: String(config.temporary?.poles_each ?? 0),
    permanentLights: String(config.permanent?.lights_per_ft ?? 0),
    permanentPoles: String(config.permanent?.poles_each ?? 0),
  };
}

export function BistroPricingSettingsCard() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const { data: pricing, isPending } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(workspaceId!),
    enabled: !!workspaceId,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const serverValue = pricing?.bistro;
  const [draft, setDraft] = useState<DraftFields | null>(null);
  const [serverBistro, setServerBistro] = useState<BistroConfig | null>(null);

  if (serverValue && serverValue !== serverBistro) {
    setServerBistro(serverValue);
    setDraft(toDraft(serverValue));
  }

  const mutation = useSettingsSaveMutation({
    mutationFn: (bistro: BistroConfig) => salesWizardApi.updatePricing(workspaceId!, { bistro }),
    successMessage: "Bistro pricing is up to date.",
    errorMessage: "We couldn't save Bistro pricing. Check your connection and try again.",
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.salesWizard.pricing(workspaceId ?? ""), updated);
    },
  });

  const disabled = mutation.isPending || !serverBistro || !draft;
  const patch = (fields: Partial<DraftFields>) =>
    setDraft((current) => (current ? { ...current, ...fields } : current));

  const save = () => {
    if (!serverBistro || !draft) return;
    const minimum = Number.parseFloat(draft.minimum);
    const rates = [
      Number.parseFloat(draft.temporaryLights),
      Number.parseFloat(draft.temporaryPoles),
      Number.parseFloat(draft.permanentLights),
      Number.parseFloat(draft.permanentPoles),
    ];
    if (!Number.isFinite(minimum) || minimum < 0) {
      toast.error("Job minimum must be a number ≥ 0");
      return;
    }
    if (rates.some((rate) => !Number.isFinite(rate) || rate < 0)) {
      toast.error("Every Bistro rate must be a valid number ≥ 0");
      return;
    }
    if (draft.enabled && rates.some((rate) => rate <= 0)) {
      toast.error("Every active Bistro light and pole rate must be greater than 0");
      return;
    }

    mutation.mutate({
      ...serverBistro,
      enabled: draft.enabled,
      minimum,
      temporary: {
        ...(serverBistro.temporary ?? DEFAULT_TEMPORARY),
        lights_per_ft: rates[0],
        poles_each: rates[1],
      },
      permanent: {
        ...(serverBistro.permanent ?? DEFAULT_PERMANENT),
        lights_per_ft: rates[2],
        poles_each: rates[3],
      },
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

  const rateFields = [
    ["bistro-temporary-lights", "Temporary lights per foot ($)", "temporaryLights"],
    ["bistro-temporary-poles", "Temporary poles/supports each ($)", "temporaryPoles"],
    ["bistro-permanent-lights", "Permanent Bistro lights per foot ($)", "permanentLights"],
    ["bistro-permanent-poles", "Permanent Bistro poles/supports each ($)", "permanentPoles"],
  ] as const;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>Bistro Lighting</CardTitle>
            <CardDescription>
              Set the base light rate per measured foot and support price per marked pole. Existing
              financing fees and commission adjustments still apply when the server builds a quote.
            </CardDescription>
          </div>
          <Switch
            checked={draft.enabled}
            onCheckedChange={(enabled) => patch({ enabled })}
            disabled={disabled}
            aria-label="Offer Bistro lighting"
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {rateFields.map(([id, label, field]) => (
            <div className="space-y-2" key={id}>
              <Label htmlFor={id}>{label}</Label>
              <Input
                id={id}
                type="number"
                min={0}
                step="0.01"
                value={draft[field]}
                onChange={(event) => patch({ [field]: event.target.value })}
                disabled={disabled}
              />
            </div>
          ))}
          <div className="space-y-2">
            <Label htmlFor="bistro-minimum">Bistro job minimum ($)</Label>
            <Input
              id="bistro-minimum"
              type="number"
              min={0}
              step="0.01"
              value={draft.minimum}
              onChange={(event) => patch({ minimum: event.target.value })}
              disabled={disabled}
            />
          </div>
        </div>

        <Separator />

        <p className="text-sm text-muted-foreground">
          Permanent holiday lighting uses its separate kit-and-COGS calculator below; these
          permanent Bistro rates do not change it.
        </p>

        <div className="flex justify-end">
          <Button className="w-full sm:w-auto" type="button" onClick={save} disabled={disabled}>
            {mutation.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Saving…
              </>
            ) : (
              "Save Bistro pricing"
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
