"use client";

/**
 * Settings → Pricing: good/better/best tiers for a non-seasonal service.
 *
 * The seasonal side has sold Good/Better/Best for a while; roofing, siding, and
 * gutters — the jobs that actually pay the bills — got a flat line-item list.
 * This editor closes that gap using the same shapes: a category declares its
 * scope items once, each tier lists the ones it covers, and the shared engine
 * prices the ladder. A three-tier ladder with a steered middle option is the
 * point, so a brand-new category starts as exactly that.
 *
 * Presentational and category-scoped: the parent tab owns the draft list and the
 * save, so switching categories in the selector never loses an unsaved edit.
 */
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";

import { PackageGrid } from "@/components/estimator/package-grid";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Textarea } from "@/components/ui/textarea";
import type {
  ServiceInclusion,
  ServicePackage,
  ServicePackageConfig,
} from "@/types/sales-wizard";

import { cid, slugify, uniqueKey } from "./editor-keys";
import { PackageCopyFields } from "./package-copy-fields";

// The preview below renders the real client-facing grid, so it needs the real
// client-facing stylesheet.
import "@/components/estimator/estimator.css";

export type ServiceBasis = "flat" | "per_unit";

/** A scope item (`ServiceInclusion`) being edited. */
export interface EditInclusion {
  _cid: string;
  key: string;
  label: string;
  price: number;
  perUnit: boolean;
}

/**
 * A tier being edited. `src` preserves the fields this editor doesn't expose
 * (card_tier, warranty) so a save round-trips them untouched; `inclusionCids`
 * references EditInclusion._cid so the coverage set survives key assignment.
 */
export interface EditTier {
  _cid: string;
  key: string;
  label: string;
  name: string;
  experience: string;
  points: string;
  valueTag: string;
  basePrice: number;
  perUnitPrice: number;
  popular: boolean;
  recommended: boolean;
  inclusionCids: string[];
  src: ServicePackage | null;
}

export interface EditServiceCategory {
  _cid: string;
  /** Backend key, frozen once saved (matches the catalog's service_category). */
  serviceCategory: string;
  label: string;
  enabled: boolean;
  basis: ServiceBasis;
  unitLabel: string;
  priceNote: string;
  minimum: number;
  perks: string; // one per line
  inclusions: EditInclusion[];
  tiers: EditTier[];
  src: ServicePackageConfig | null;
}

function blankTier(overrides: Partial<EditTier> = {}): EditTier {
  return {
    _cid: cid(),
    key: "",
    label: "",
    name: "",
    experience: "",
    points: "",
    valueTag: "",
    basePrice: 0,
    perUnitPrice: 0,
    popular: false,
    recommended: false,
    inclusionCids: [],
    src: null,
    ...overrides,
  };
}

/**
 * A brand-new category: three tiers with the middle one steered.
 *
 * Mirrors the server's default for a category created outside this editor, so
 * an operator gets the same ladder either way. Prices stay 0 — a half-configured
 * category must never quote a number nobody typed.
 */
export function newServiceCategoryDraft(): EditServiceCategory {
  return {
    _cid: cid(),
    serviceCategory: "",
    label: "",
    enabled: false,
    basis: "per_unit",
    unitLabel: "sq ft",
    priceNote: "",
    minimum: 0,
    perks: "",
    inclusions: [],
    src: null,
    tiers: [
      blankTier({ label: "Good", name: "Essential" }),
      blankTier({
        label: "Better",
        name: "Preferred",
        popular: true,
        recommended: true,
      }),
      blankTier({ label: "Best", name: "Premier" }),
    ],
  };
}

/** Seed the editor from the saved config, low→high by `package_order`. */
export function toServiceCategoryDrafts(
  configs: ServicePackageConfig[],
): EditServiceCategory[] {
  return configs.map((config) => {
    const inclusions: EditInclusion[] = (config.inclusions ?? []).map((i) => ({
      _cid: cid(),
      key: i.key,
      label: i.label,
      price: i.price ?? 0,
      perUnit: i.per_unit ?? false,
    }));
    const keyToCid = new Map(inclusions.map((i) => [i.key, i._cid] as const));

    const tiers: EditTier[] = (config.packages ?? []).map((p) => ({
      _cid: cid(),
      key: p.key,
      label: p.label,
      name: p.name ?? "",
      experience: p.experience ?? "",
      points: (p.points ?? []).join("\n"),
      valueTag: p.value_tag ?? "",
      basePrice: p.base_price ?? 0,
      perUnitPrice: p.per_unit_price ?? 0,
      popular: p.popular ?? false,
      recommended: p.recommended ?? false,
      // Unknown keys (a deleted scope item) are dropped rather than kept as a
      // dangling reference the engine would ignore anyway.
      inclusionCids: (p.inclusion_keys ?? [])
        .map((k) => keyToCid.get(k))
        .filter((c): c is string => Boolean(c)),
      src: p,
    }));

    const order = config.package_order ?? [];
    if (order.length) {
      const rank = new Map(order.map((k, i) => [k, i] as const));
      const rankOf = (k: string) => rank.get(k) ?? Number.MAX_SAFE_INTEGER;
      tiers.sort((a, b) => rankOf(a.key) - rankOf(b.key));
    }

    return {
      _cid: cid(),
      serviceCategory: config.service_category,
      label: config.label,
      enabled: config.enabled ?? false,
      basis: config.basis === "flat" ? "flat" : "per_unit",
      unitLabel: config.unit_label ?? "sq ft",
      priceNote: config.price_note ?? "",
      minimum: config.minimum ?? 0,
      perks: (config.perks ?? []).join("\n"),
      inclusions,
      tiers,
      src: config,
    };
  });
}

export type BuildResult =
  | { ok: true; value: ServicePackageConfig }
  | { ok: false; error: string };

/**
 * Validate a draft and freeze keys for new rows.
 *
 * Used-key sets are pre-seeded with every existing key so a freshly-named row
 * can never collide with one assigned later in the list — the same discipline
 * the seasonal editor uses, for the same reason: these keys are what saved
 * quotes and shared links resolve selections by.
 */
export function buildServiceCategory(
  draft: EditServiceCategory,
  usedCategoryKeys: Set<string>,
): BuildResult {
  const label = draft.label.trim();
  if (!label) return { ok: false, error: "Every service needs a name" };
  if (draft.tiers.length === 0) {
    return { ok: false, error: `"${label}" needs at least one package` };
  }

  const categoryKey =
    draft.serviceCategory || uniqueKey(slugify(label, "service"), usedCategoryKeys);

  const usedInclusionKeys = new Set(
    draft.inclusions.map((i) => i.key).filter(Boolean),
  );
  const cidToKey = new Map<string, string>();
  const inclusions: ServiceInclusion[] = [];
  for (const inclusion of draft.inclusions) {
    const name = inclusion.label.trim();
    if (!name) {
      return { ok: false, error: `Every included item in "${label}" needs a name` };
    }
    if (!Number.isFinite(inclusion.price) || inclusion.price < 0) {
      return { ok: false, error: `"${name}" price must be a number ≥ 0` };
    }
    const key = inclusion.key || uniqueKey(slugify(name, "item"), usedInclusionKeys);
    cidToKey.set(inclusion._cid, key);
    inclusions.push({
      key,
      label: name,
      price: inclusion.price,
      per_unit: inclusion.perUnit,
    });
  }

  const usedTierKeys = new Set(draft.tiers.map((t) => t.key).filter(Boolean));
  const packages: ServicePackage[] = [];
  for (const tier of draft.tiers) {
    const tierLabel = tier.label.trim();
    if (!tierLabel) {
      return { ok: false, error: `Every package in "${label}" needs a name` };
    }
    for (const [field, amount] of [
      ["base price", tier.basePrice],
      ["per-unit price", tier.perUnitPrice],
    ] as const) {
      if (!Number.isFinite(amount) || amount < 0) {
        return { ok: false, error: `"${tierLabel}" ${field} must be a number ≥ 0` };
      }
    }
    const src = tier.src;
    packages.push({
      key: tier.key || uniqueKey(slugify(tierLabel, "package"), usedTierKeys),
      label: tierLabel,
      name: tier.name.trim() || null,
      marker: src?.marker ?? null,
      card_tier: src?.card_tier ?? null,
      experience: tier.experience.trim() || null,
      warranty: src?.warranty ?? null,
      points: tier.points
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      value_tag: tier.valueTag.trim() || null,
      popular: tier.popular,
      recommended: tier.recommended,
      base_price: tier.basePrice,
      per_unit_price: tier.perUnitPrice,
      inclusion_keys: tier.inclusionCids
        .map((c) => cidToKey.get(c))
        .filter((k): k is string => Boolean(k)),
    });
  }

  if (!Number.isFinite(draft.minimum) || draft.minimum < 0) {
    return { ok: false, error: `"${label}" job minimum must be a number ≥ 0` };
  }

  return {
    ok: true,
    value: {
      ...draft.src,
      service_category: categoryKey,
      label,
      enabled: draft.enabled,
      basis: draft.basis,
      unit_label: draft.unitLabel.trim() || "sq ft",
      price_note: draft.priceNote.trim() || null,
      minimum: draft.minimum,
      perks: draft.perks
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      inclusions,
      package_order: packages.map((p) => p.key),
      packages,
    },
  };
}

interface ServicePackagesEditorProps {
  draft: EditServiceCategory;
  onChange: (patch: Partial<EditServiceCategory>) => void;
  onRemove: () => void;
  disabled?: boolean;
}

export function ServicePackagesEditor({
  draft,
  onChange,
  onRemove,
  disabled,
}: ServicePackagesEditorProps) {
  const perUnit = draft.basis === "per_unit";
  const unit = draft.unitLabel.trim() || "sq ft";

  const patchTier = (tierCid: string, patch: Partial<EditTier>) =>
    onChange({
      tiers: draft.tiers.map((t) =>
        t._cid === tierCid ? { ...t, ...patch } : t,
      ),
    });

  // Exactly one tier is steered: flagging a new one clears the old flag, so the
  // ladder can never ship with two "Recommended" badges.
  const setRecommended = (tierCid: string, on: boolean) =>
    onChange({
      tiers: draft.tiers.map((t) => {
        if (t._cid === tierCid) return { ...t, recommended: on };
        return on && t.recommended ? { ...t, recommended: false } : t;
      }),
    });

  const moveTier = (tierCid: string, dir: -1 | 1) => {
    const i = draft.tiers.findIndex((t) => t._cid === tierCid);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= draft.tiers.length) return;
    const next = [...draft.tiers];
    [next[i], next[j]] = [next[j], next[i]];
    onChange({ tiers: next });
  };

  const toggleInclusion = (tierCid: string, inclusionCid: string, on: boolean) => {
    const current = draft.tiers.find((t) => t._cid === tierCid)?.inclusionCids ?? [];
    const without = current.filter((c) => c !== inclusionCid);
    patchTier(tierCid, { inclusionCids: on ? [...without, inclusionCid] : without });
  };

  // The operator's own numbers echoed back into the client-facing grid — no
  // money math happens here. The engine's gross-up, inclusions, and job minimum
  // are deliberately not simulated, which is why the caption says "from".
  const preview = draft.tiers.map((tier) => ({
    key: tier._cid,
    name: tier.name.trim() || tier.label.trim() || "Untitled package",
    total: perUnit ? tier.perUnitPrice : tier.basePrice,
    valueTag: tier.valueTag.trim() || null,
    popular: tier.popular,
    recommended: tier.recommended,
    points: tier.points
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean),
    experience: tier.experience.trim() || null,
  }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2 flex-1 min-w-[200px]">
          <Label htmlFor={`svc-label-${draft._cid}`}>Service name</Label>
          <Input
            id={`svc-label-${draft._cid}`}
            placeholder="e.g. Roof Replacement"
            value={draft.label}
            onChange={(e) => onChange({ label: e.target.value })}
            disabled={disabled}
          />
          <p className="text-xs text-muted-foreground">
            {draft.serviceCategory
              ? `Price-book category: ${draft.serviceCategory}`
              : "Saved as a price-book category the first time you save."}
          </p>
        </div>
        <div className="flex items-center gap-3 pb-1">
          <div className="space-y-0.5">
            <Label htmlFor={`svc-enabled-${draft._cid}`}>Sell as packages</Label>
            <p className="text-xs text-muted-foreground">
              Off keeps this service à la carte.
            </p>
          </div>
          <Switch
            id={`svc-enabled-${draft._cid}`}
            checked={draft.enabled}
            onCheckedChange={(v) => onChange({ enabled: v })}
            disabled={disabled}
            aria-label={`Sell ${draft.label || "this service"} as packages`}
          />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onRemove}
          disabled={disabled}
          aria-label={`Remove ${draft.label || "service"}`}
        >
          <Trash2 className="size-4 text-destructive" />
        </Button>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="space-y-2 w-48">
          <Label>Priced by</Label>
          <Select
            value={draft.basis}
            onValueChange={(v) => onChange({ basis: v as ServiceBasis })}
            disabled={disabled}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="per_unit">Per measured unit</SelectItem>
              <SelectItem value="flat">Flat price per job</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2 w-40">
          <Label>Unit name</Label>
          <Input
            placeholder="e.g. squares, sq ft"
            value={draft.unitLabel}
            onChange={(e) => onChange({ unitLabel: e.target.value })}
            disabled={disabled || !perUnit}
          />
        </div>
        <div className="space-y-2 w-40">
          <Label>Job minimum ($)</Label>
          <Input
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            value={Number.isFinite(draft.minimum) ? draft.minimum : ""}
            onChange={(e) =>
              onChange({ minimum: Number.parseFloat(e.target.value) || 0 })
            }
            disabled={disabled}
          />
        </div>
        <div className="space-y-2 flex-1 min-w-[180px]">
          <Label>Price caption</Label>
          <Input
            placeholder="e.g. One-time install"
            value={draft.priceNote}
            onChange={(e) => onChange({ priceNote: e.target.value })}
            disabled={disabled}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label>Why customers buy this service</Label>
        <Textarea
          rows={3}
          placeholder={
            "One per line, e.g.\nManufacturer-backed warranty\nCrews on staff, never subbed out"
          }
          value={draft.perks}
          onChange={(e) => onChange({ perks: e.target.value })}
          disabled={disabled}
        />
        <p className="text-xs text-muted-foreground">One bullet per line.</p>
      </div>

      <Separator />

      <div className="space-y-4">
        <div className="space-y-1">
          <h3 className="text-base font-semibold">What can be included</h3>
          <p className="text-sm text-muted-foreground">
            Declare each upgrade once, then tick it on the packages that cover
            it. Widening a package is what makes the next tier worth more.
          </p>
        </div>

        {draft.inclusions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No upgrades yet. Packages can still be priced on their own rate.
          </p>
        ) : null}

        {draft.inclusions.map((inclusion) => (
          <div key={inclusion._cid} className="flex flex-wrap items-end gap-3">
            <div className="space-y-1 flex-1 min-w-[180px]">
              <Label className="text-xs text-muted-foreground">Item</Label>
              <Input
                placeholder="e.g. Ice & water shield"
                value={inclusion.label}
                onChange={(e) =>
                  onChange({
                    inclusions: draft.inclusions.map((i) =>
                      i._cid === inclusion._cid
                        ? { ...i, label: e.target.value }
                        : i,
                    ),
                  })
                }
                disabled={disabled}
              />
            </div>
            <div className="space-y-1 w-36">
              <Label className="text-xs text-muted-foreground">
                {inclusion.perUnit ? `$ / ${unit}` : "$ flat"}
              </Label>
              <Input
                type="number"
                min={0}
                step="0.01"
                inputMode="decimal"
                value={Number.isFinite(inclusion.price) ? inclusion.price : ""}
                onChange={(e) =>
                  onChange({
                    inclusions: draft.inclusions.map((i) =>
                      i._cid === inclusion._cid
                        ? { ...i, price: Number.parseFloat(e.target.value) || 0 }
                        : i,
                    ),
                  })
                }
                disabled={disabled}
              />
            </div>
            <div className="flex items-center gap-2 pb-2">
              <Checkbox
                id={`inc-perunit-${inclusion._cid}`}
                checked={inclusion.perUnit}
                onCheckedChange={(v) =>
                  onChange({
                    inclusions: draft.inclusions.map((i) =>
                      i._cid === inclusion._cid ? { ...i, perUnit: v === true } : i,
                    ),
                  })
                }
                disabled={disabled || !perUnit}
              />
              <Label
                htmlFor={`inc-perunit-${inclusion._cid}`}
                className="text-sm font-normal"
              >
                Per {unit}
              </Label>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() =>
                onChange({
                  inclusions: draft.inclusions.filter(
                    (i) => i._cid !== inclusion._cid,
                  ),
                })
              }
              disabled={disabled}
              aria-label={`Remove ${inclusion.label || "item"}`}
            >
              <Trash2 className="size-4 text-muted-foreground" />
            </Button>
          </div>
        ))}

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            onChange({
              inclusions: [
                ...draft.inclusions,
                { _cid: cid(), key: "", label: "", price: 0, perUnit: false },
              ],
            })
          }
          disabled={disabled}
        >
          <Plus className="size-4" /> Add included item
        </Button>
      </div>

      <Separator />

      <div className="space-y-4">
        <div className="space-y-1">
          <h3 className="text-base font-semibold">Packages</h3>
          <p className="text-sm text-muted-foreground">
            Order runs low → high. Steer one package — usually the middle — and
            it gets the Recommended badge on the customer&apos;s page.
          </p>
        </div>

        {draft.tiers.map((tier, idx) => (
          <div
            key={tier._cid}
            className="rounded-lg border p-4 space-y-4 bg-muted/20"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-medium text-muted-foreground">
                Package {idx + 1}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => moveTier(tier._cid, -1)}
                  disabled={disabled || idx === 0}
                  aria-label={`Move ${tier.label || "package"} up`}
                >
                  <ChevronUp className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => moveTier(tier._cid, 1)}
                  disabled={disabled || idx === draft.tiers.length - 1}
                  aria-label={`Move ${tier.label || "package"} down`}
                >
                  <ChevronDown className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() =>
                    onChange({
                      tiers: draft.tiers.filter((t) => t._cid !== tier._cid),
                    })
                  }
                  disabled={disabled}
                  aria-label={`Remove ${tier.label || "package"}`}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              </div>
            </div>

            <PackageCopyFields
              value={tier}
              onChange={(patch) => patchTier(tier._cid, patch)}
              disabled={disabled}
              labelPlaceholder="e.g. Better"
              namePlaceholder="e.g. Preferred"
              experiencePlaceholder="A sentence or two on what this package is like to live with…"
              pointsPlaceholder={
                "One per line, e.g.\nEverything in Essential\nUpgraded materials"
              }
            />

            <div className="flex flex-wrap gap-3">
              <div className="space-y-2 w-40">
                <Label>Base price ($)</Label>
                <Input
                  type="number"
                  min={0}
                  step="0.01"
                  inputMode="decimal"
                  value={Number.isFinite(tier.basePrice) ? tier.basePrice : ""}
                  onChange={(e) =>
                    patchTier(tier._cid, {
                      basePrice: Number.parseFloat(e.target.value) || 0,
                    })
                  }
                  disabled={disabled}
                />
              </div>
              <div className="space-y-2 w-40">
                <Label>$ / {unit}</Label>
                <Input
                  type="number"
                  min={0}
                  step="0.01"
                  inputMode="decimal"
                  value={
                    Number.isFinite(tier.perUnitPrice) ? tier.perUnitPrice : ""
                  }
                  onChange={(e) =>
                    patchTier(tier._cid, {
                      perUnitPrice: Number.parseFloat(e.target.value) || 0,
                    })
                  }
                  disabled={disabled || !perUnit}
                />
              </div>
              <div className="space-y-2 flex-1 min-w-[160px]">
                <Label>Value tag</Label>
                <Input
                  placeholder="e.g. Lifetime system"
                  value={tier.valueTag}
                  onChange={(e) =>
                    patchTier(tier._cid, { valueTag: e.target.value })
                  }
                  disabled={disabled}
                />
              </div>
            </div>

            <div className="flex flex-wrap gap-6">
              <div className="flex items-center gap-3">
                <Switch
                  id={`tier-rec-${tier._cid}`}
                  checked={tier.recommended}
                  onCheckedChange={(v) => setRecommended(tier._cid, v)}
                  disabled={disabled}
                  aria-label={`Recommend ${tier.label || "package"}`}
                />
                <Label htmlFor={`tier-rec-${tier._cid}`}>Recommended</Label>
              </div>
              <div className="flex items-center gap-3">
                <Switch
                  id={`tier-pop-${tier._cid}`}
                  checked={tier.popular}
                  onCheckedChange={(v) => patchTier(tier._cid, { popular: v })}
                  disabled={disabled}
                  aria-label={`Mark ${tier.label || "package"} most popular`}
                />
                <Label htmlFor={`tier-pop-${tier._cid}`}>Most popular</Label>
              </div>
            </div>

            {draft.inclusions.length > 0 ? (
              <div className="space-y-2">
                <Label>Included upgrades</Label>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {draft.inclusions.map((inclusion) => {
                    const cbId = `tier-${tier._cid}-inc-${inclusion._cid}`;
                    return (
                      <div key={inclusion._cid} className="flex items-center gap-2">
                        <Checkbox
                          id={cbId}
                          checked={tier.inclusionCids.includes(inclusion._cid)}
                          onCheckedChange={(v) =>
                            toggleInclusion(tier._cid, inclusion._cid, v === true)
                          }
                          disabled={disabled}
                        />
                        <Label htmlFor={cbId} className="text-sm font-normal">
                          {inclusion.label || "Untitled item"}
                        </Label>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        ))}

        <Button
          type="button"
          variant="outline"
          onClick={() => onChange({ tiers: [...draft.tiers, blankTier()] })}
          disabled={disabled}
        >
          <Plus className="size-4" /> Add package
        </Button>
      </div>

      <Separator />

      <div className="space-y-3">
        <div className="space-y-1">
          <h3 className="text-base font-semibold">Customer preview</h3>
          <p className="text-sm text-muted-foreground">
            The same cards the customer sees on a shared proposal. Prices shown
            are the rates you typed — the final total also picks up your included
            upgrades, job minimum, and financing.
          </p>
        </div>
        <div className="cmp-view cmp-embedded rounded-lg border bg-[#0a0a0a] p-4">
          <PackageGrid
            packages={preview}
            copy={{
              title: draft.label.trim()
                ? `Choose your ${draft.label.trim().toLowerCase()}`
                : "Choose your package",
              blurb:
                "Three ways to do the job. Most customers pick the middle one.",
              priceNote: draft.priceNote.trim() || (perUnit ? `Per ${unit}` : "Per job"),
            }}
          />
        </div>
      </div>
    </div>
  );
}
