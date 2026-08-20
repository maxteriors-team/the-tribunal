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
import type { PermanentConfig } from "@/types/sales-wizard";

interface DraftPackage {
  feet: string;
  cost: string;
}

interface DraftFields {
  enabled: boolean;
  label: string;
  easyMarkup: string;
  standardMarkup: string;
  complexMarkup: string;
  minimum: string;
  packages: DraftPackage[];
}

function toDraft(config: PermanentConfig): DraftFields {
  return {
    enabled: config.enabled,
    label: config.label ?? "Permanent Holiday Lighting",
    easyMarkup: String(config.easy_markup ?? 2.5),
    standardMarkup: String(config.standard_markup ?? 3),
    complexMarkup: String(config.complex_markup ?? 3.5),
    minimum: String(config.minimum ?? 0),
    packages: (config.packages ?? []).map((kit) => ({
      feet: String(kit.feet),
      cost: String(kit.cost),
    })),
  };
}

export function PermanentPricingSettingsCard() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const { data: pricing, isPending } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(workspaceId!),
    enabled: !!workspaceId,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const [draft, setDraft] = useState<DraftFields | null>(null);
  const [serverPermanent, setServerPermanent] = useState<PermanentConfig | null>(null);

  if (pricing?.permanent && pricing.permanent !== serverPermanent) {
    setServerPermanent(pricing.permanent);
    setDraft(toDraft(pricing.permanent));
  }

  const mutation = useSettingsSaveMutation({
    mutationFn: (permanent: PermanentConfig) =>
      salesWizardApi.updatePricing(workspaceId!, { permanent }),
    successMessage: "Permanent lighting package pricing is up to date.",
    errorMessage:
      "We couldn't save permanent lighting pricing. Check your connection and try again.",
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.salesWizard.pricing(workspaceId ?? ""), updated);
    },
  });

  const disabled = mutation.isPending || !serverPermanent || !draft;
  const patch = (fields: Partial<DraftFields>) =>
    setDraft((current) => (current ? { ...current, ...fields } : current));

  const patchPackage = (index: number, fields: Partial<DraftPackage>) =>
    setDraft((current) =>
      current
        ? {
            ...current,
            packages: current.packages.map((kit, kitIndex) =>
              kitIndex === index ? { ...kit, ...fields } : kit,
            ),
          }
        : current,
    );

  const save = () => {
    if (!serverPermanent || !draft) return;
    const easyMarkup = Number.parseFloat(draft.easyMarkup);
    const standardMarkup = Number.parseFloat(draft.standardMarkup);
    const complexMarkup = Number.parseFloat(draft.complexMarkup);
    const minimum = Number.parseFloat(draft.minimum);
    const packages = draft.packages.map((kit) => ({
      feet: Number.parseInt(kit.feet, 10),
      cost: Number.parseFloat(kit.cost),
    }));
    if (
      [easyMarkup, standardMarkup, complexMarkup].some(
        (value) => !Number.isFinite(value) || value <= 0,
      )
    ) {
      toast.error("Every complexity multiplier must be greater than 0");
      return;
    }
    if (!Number.isFinite(minimum) || minimum < 0) {
      toast.error("Job minimum must be a number ≥ 0");
      return;
    }
    if (
      packages.length === 0 ||
      packages.some(
        (kit) =>
          !Number.isInteger(kit.feet) ||
          kit.feet <= 0 ||
          !Number.isFinite(kit.cost) ||
          kit.cost < 0,
      )
    ) {
      toast.error("Every kit needs positive footage and a valid COGS amount");
      return;
    }
    const label = draft.label.trim();
    if (!label) {
      toast.error("Give the offering a name");
      return;
    }
    mutation.mutate({
      ...serverPermanent,
      enabled: draft.enabled,
      label,
      easy_markup: easyMarkup,
      standard_markup: standardMarkup,
      complex_markup: complexMarkup,
      markup: complexMarkup,
      minimum,
      packages,
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
              Measured footage rounds up to the smallest Minleon kit that covers the job. Customer
              price equals kit COGS multiplied by your markup.
            </CardDescription>
          </div>
          <Switch
            checked={draft.enabled}
            onCheckedChange={(enabled) => patch({ enabled })}
            disabled={disabled}
            aria-label="Offer permanent holiday lighting"
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="perm-easy-markup">Easy multiplier</Label>
            <Input
              id="perm-easy-markup"
              type="number"
              min={0.01}
              step="0.1"
              value={draft.easyMarkup}
              onChange={(event) => patch({ easyMarkup: event.target.value })}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="perm-standard-markup">Standard multiplier</Label>
            <Input
              id="perm-standard-markup"
              type="number"
              min={0.01}
              step="0.1"
              value={draft.standardMarkup}
              onChange={(event) => patch({ standardMarkup: event.target.value })}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="perm-complex-markup">Complex multiplier</Label>
            <Input
              id="perm-complex-markup"
              type="number"
              min={0.01}
              step="0.1"
              value={draft.complexMarkup}
              onChange={(event) => patch({ complexMarkup: event.target.value })}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="perm-minimum">Job minimum ($)</Label>
            <Input
              id="perm-minimum"
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

        <div className="space-y-3">
          <div>
            <h3 className="font-medium">Minleon complete kits</h3>
            <p className="text-xs text-muted-foreground">
              Enter supplier COGS. A 165-ft measurement selects the 200-ft kit.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {draft.packages.map((kit, index) => (
              <div className="grid grid-cols-2 gap-2" key={index}>
                <div className="space-y-1">
                  <Label htmlFor={`perm-kit-feet-${index}`}>Kit footage</Label>
                  <Input
                    id={`perm-kit-feet-${index}`}
                    type="number"
                    min={1}
                    step={1}
                    value={kit.feet}
                    onChange={(event) => patchPackage(index, { feet: event.target.value })}
                    disabled={disabled}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`perm-kit-cost-${index}`}>COGS ($)</Label>
                  <Input
                    id={`perm-kit-cost-${index}`}
                    type="number"
                    min={0}
                    step="0.01"
                    value={kit.cost}
                    onChange={(event) => patchPackage(index, { cost: event.target.value })}
                    disabled={disabled}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <Separator />

        <div className="space-y-2 max-w-md">
          <Label htmlFor="perm-label">Offering name</Label>
          <Input
            id="perm-label"
            value={draft.label}
            onChange={(event) => patch({ label: event.target.value })}
            disabled={disabled}
          />
        </div>

        <div className="flex justify-end">
          <Button className="w-full sm:w-auto" type="button" onClick={save} disabled={disabled}>
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
