"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { inventoryApi } from "@/lib/api/inventory";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import type { InventoryItem } from "@/types/inventory";
import type { BistroConfig, BistroInstallationConfig } from "@/types/sales-wizard";

interface DraftFields {
  enabled: boolean;
  minimum: string;
  temporaryLights: string;
  temporaryPoles: string;
  permanentLights: string;
  permanentPoles: string;
  temporaryLightsSku: string;
  temporaryPolesSku: string;
  permanentLightsSku: string;
  permanentPolesSku: string;
  temporaryCoverage: string;
}

type BistroInventoryInstallationConfig = BistroInstallationConfig & {
  lights_inventory_sku?: string | null;
  poles_inventory_sku?: string | null;
  stock_feet_per_light_unit?: number;
};

const ACTIVE_INVENTORY_PARAMS = { include_inactive: false, page_size: 100 } as const;
const NO_SKU = "__none__";

const DEFAULT_TEMPORARY: BistroInventoryInstallationConfig = {
  label: "Temporary Bistro Lighting",
  lights_per_ft: 0,
  poles_each: 0,
  lights_inventory_sku: null,
  poles_inventory_sku: null,
  stock_feet_per_light_unit: 200,
};
const DEFAULT_PERMANENT: BistroInventoryInstallationConfig = {
  label: "Permanent Bistro Lighting",
  lights_per_ft: 0,
  poles_each: 0,
  lights_inventory_sku: null,
  poles_inventory_sku: null,
  stock_feet_per_light_unit: 1,
};

function toDraft(config: BistroConfig): DraftFields {
  const temporary = (config.temporary ?? DEFAULT_TEMPORARY) as BistroInventoryInstallationConfig;
  const permanent = (config.permanent ?? DEFAULT_PERMANENT) as BistroInventoryInstallationConfig;
  return {
    enabled: config.enabled,
    minimum: String(config.minimum ?? 0),
    temporaryLights: String(temporary.lights_per_ft ?? 0),
    temporaryPoles: String(temporary.poles_each ?? 0),
    permanentLights: String(permanent.lights_per_ft ?? 0),
    permanentPoles: String(permanent.poles_each ?? 0),
    temporaryLightsSku: temporary.lights_inventory_sku ?? "",
    temporaryPolesSku: temporary.poles_inventory_sku ?? "",
    permanentLightsSku: permanent.lights_inventory_sku ?? "",
    permanentPolesSku: permanent.poles_inventory_sku ?? "",
    temporaryCoverage: String(temporary.stock_feet_per_light_unit ?? 200),
  };
}

interface InventorySkuSelectProps {
  id: string;
  label: string;
  value: string;
  items: Array<InventoryItem & { sku: string }>;
  disabled: boolean;
  onChange: (value: string) => void;
}

function InventorySkuSelect({
  id,
  label,
  value,
  items,
  disabled,
  onChange,
}: InventorySkuSelectProps) {
  const unavailable = value && !items.some((item) => item.sku === value);
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Select
        value={value || NO_SKU}
        onValueChange={(next) => onChange(next === NO_SKU ? "" : next)}
        disabled={disabled}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder="Not connected" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_SKU}>Not connected</SelectItem>
          {unavailable ? (
            <SelectItem value={value} disabled>
              {value} — unavailable
            </SelectItem>
          ) : null}
          {items.map((item) => (
            <SelectItem key={item.id} value={item.sku}>
              {item.name} — {item.sku} ({item.unit_of_measure})
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
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
  const {
    data: inventory,
    isPending: inventoryPending,
    isError: inventoryError,
  } = useQuery({
    queryKey: queryKeys.inventory.list(workspaceId ?? "", ACTIVE_INVENTORY_PARAMS),
    queryFn: () => inventoryApi.listItems(workspaceId!, ACTIVE_INVENTORY_PARAMS),
    enabled: !!workspaceId,
    staleTime: 30_000,
  });
  const skuItems = (inventory?.items ?? []).filter(
    (item): item is InventoryItem & { sku: string } => item.is_active && !!item.sku,
  );
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
    const temporaryCoverage = Number.parseFloat(draft.temporaryCoverage);
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
    if (!Number.isFinite(temporaryCoverage) || temporaryCoverage <= 0) {
      toast.error("Temporary set coverage must be greater than 0 feet");
      return;
    }
    const permanentSkus = new Set(
      [draft.permanentLightsSku, draft.permanentPolesSku].filter(Boolean),
    );
    const conflict = [draft.temporaryLightsSku, draft.temporaryPolesSku].find((sku) =>
      permanentSkus.has(sku),
    );
    if (conflict) {
      toast.error(`${conflict} cannot be both permanent stock and reusable equipment`);
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
        lights_inventory_sku: draft.temporaryLightsSku || null,
        poles_inventory_sku: draft.temporaryPolesSku || null,
        stock_feet_per_light_unit: temporaryCoverage,
      },
      permanent: {
        ...(serverBistro.permanent ?? DEFAULT_PERMANENT),
        lights_per_ft: rates[2],
        poles_each: rates[3],
        lights_inventory_sku: draft.permanentLightsSku || null,
        poles_inventory_sku: draft.permanentPolesSku || null,
        stock_feet_per_light_unit: 1,
      },
    } as BistroConfig);
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

        <div className="space-y-4">
          <div className="space-y-1">
            <h3 className="text-sm font-medium">Inventory mapping</h3>
            <p className="text-sm text-muted-foreground">
              Permanent units are consumed and post COGS. Temporary units are deployed, then
              returned for reuse.
            </p>
          </div>
          {inventoryError ? (
            <p className="text-sm text-destructive" role="alert">
              Active inventory items could not be loaded. Pricing can still be saved unchanged.
            </p>
          ) : null}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <InventorySkuSelect
              id="bistro-temporary-lights-sku"
              label="Temporary light-set inventory item"
              value={draft.temporaryLightsSku}
              items={skuItems}
              disabled={disabled || inventoryPending || inventoryError}
              onChange={(temporaryLightsSku) => patch({ temporaryLightsSku })}
            />
            <InventorySkuSelect
              id="bistro-temporary-poles-sku"
              label="Temporary pole inventory item"
              value={draft.temporaryPolesSku}
              items={skuItems}
              disabled={disabled || inventoryPending || inventoryError}
              onChange={(temporaryPolesSku) => patch({ temporaryPolesSku })}
            />
            <div className="space-y-2">
              <Label htmlFor="bistro-temporary-coverage">Feet covered by one temporary set</Label>
              <Input
                id="bistro-temporary-coverage"
                type="number"
                min={0.01}
                step="0.01"
                value={draft.temporaryCoverage}
                onChange={(event) => patch({ temporaryCoverage: event.target.value })}
                disabled={disabled}
              />
            </div>
            <div />
            <InventorySkuSelect
              id="bistro-permanent-lights-sku"
              label="Permanent footage inventory item"
              value={draft.permanentLightsSku}
              items={skuItems}
              disabled={disabled || inventoryPending || inventoryError}
              onChange={(permanentLightsSku) => patch({ permanentLightsSku })}
            />
            <InventorySkuSelect
              id="bistro-permanent-poles-sku"
              label="Permanent pole inventory item"
              value={draft.permanentPolesSku}
              items={skuItems}
              disabled={disabled || inventoryPending || inventoryError}
              onChange={(permanentPolesSku) => patch({ permanentPolesSku })}
            />
          </div>
          {!inventoryPending && skuItems.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Create active inventory items with SKUs before connecting Bistro stock.
            </p>
          ) : null}
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
