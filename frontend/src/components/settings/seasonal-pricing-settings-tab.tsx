"use client";

/**
 * Settings → Pricing: the seasonal-decor editor (operator self-serve).
 *
 * Lets a non-technical operator switch the Christmas offering on, add/edit/remove
 * seasonal decor categories (trees, bushes, wreaths, garland, and anything new),
 * set the roofline base rate, price the post-season takedown and storage add-ons,
 * and pick the season dates the install/takedown Service Plans anchor on — the
 * exact `christmas` block the sales wizard, roofline estimator, and quote-approval
 * provisioner read. Saving PUTs the whole block back (the endpoint replaces blocks
 * wholesale), so every field this editor doesn't expose (`perks`, package markers,
 * …) round-trips untouched. No code change or deploy needed.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Loader2, Plus, Trash2 } from "lucide-react";
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
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type {
  ChristmasConfig,
  ChristmasPackage,
  SeasonalItem,
} from "@/types/sales-wizard";

type SeasonalUnit = "each" | "per_ft";

// Client-side working shapes. `_cid` is a stable React list key; `key` is the
// backend key (frozen once saved, assigned on save for new rows so links stay
// valid). Prices/labels are edited freely.
interface EditOption {
  _cid: string;
  key: string;
  name: string;
  price: number;
}
interface EditCategory {
  _cid: string;
  key: string;
  label: string;
  unit: SeasonalUnit;
  options: EditOption[];
}

// A seasonal package tier being edited. `key` is frozen once saved (assigned on
// save for new rows). `itemCids` references EditCategory._cid so the include set
// survives category-key assignment, resolving to SeasonalItem keys on save.
// `src` preserves the fields this editor doesn't expose (marker, card_tier,
// warranty, value_tag, popular) so a save round-trips them untouched.
interface EditPackage {
  _cid: string;
  key: string;
  label: string;
  name: string;
  experience: string;
  points: string; // one selling point per line
  includesRoofline: boolean;
  itemCids: string[];
  src: ChristmasPackage | null;
}

const cid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `cid-${Math.random().toString(36).slice(2)}`;

function slugify(value: string, fallback: string): string {
  const slug = value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || fallback;
}

// Month options for the season anchors. The shadcn Select speaks strings, so
// values are "1"…"12" and are parsed back to ints on save.
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
].map((label, i) => ({ value: String(i + 1), label }));

// How many days each month can hold. Mirrors the backend clamp in
// `ChristmasConfig._clamp_season_days`, which uses a non-leap year — February is
// 28 so a yearly plan anchor lands on a real date every year.
const MONTH_LENGTHS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function daysInMonth(month: number): number {
  return MONTH_LENGTHS[month - 1] ?? 31;
}

/**
 * Clamp a typed day down to one the chosen month actually has (Feb 31 → Feb 28).
 * Applied on every day/month edit so the operator always sees the value that will
 * be saved, instead of the backend silently rewriting it after the fact.
 */
function clampDay(day: string, month: string): string {
  const parsed = Number.parseInt(day, 10);
  if (!Number.isFinite(parsed)) return day;
  const max = daysInMonth(Number.parseInt(month, 10));
  return parsed > max ? String(max) : day;
}

/** `takedown_rate` is stored as a fraction but shown to the operator as a percent. */
function rateToPercent(rate: number): string {
  return String(Math.round(rate * 10000) / 100);
}

/** Ensure a unique key within an already-used set (append -2, -3, …). */
function uniqueKey(base: string, used: Set<string>): string {
  let candidate = base;
  let n = 2;
  while (used.has(candidate)) {
    candidate = `${base}-${n}`;
    n += 1;
  }
  used.add(candidate);
  return candidate;
}

function toEditModel(items: SeasonalItem[]): EditCategory[] {
  return items.map((item) => ({
    _cid: cid(),
    key: item.key,
    label: item.label,
    unit: item.unit === "per_ft" ? "per_ft" : "each",
    options: (item.options ?? []).map((o) => ({
      _cid: cid(),
      key: o.key,
      name: o.name,
      price: o.price ?? 0,
    })),
  }));
}

// Seed the package editor from the server config. `item_keys` resolve to the
// seeded categories' `_cid`s (unknown keys — deleted categories — are dropped),
// and packages are ordered by `package_order` (low→high) for a stable round-trip;
// unranked packages keep their declared order after the ranked ones.
function toPackageEditModel(
  packages: ChristmasPackage[],
  categories: EditCategory[],
  order: string[],
): EditPackage[] {
  const keyToCid = new Map(categories.map((c) => [c.key, c._cid] as const));
  const models: EditPackage[] = packages.map((p) => ({
    _cid: cid(),
    key: p.key,
    label: p.label,
    name: p.name ?? "",
    experience: p.experience ?? "",
    points: (p.points ?? []).join("\n"),
    includesRoofline: p.includes_roofline ?? false,
    itemCids: (p.item_keys ?? [])
      .map((k) => keyToCid.get(k))
      .filter((c): c is string => Boolean(c)),
    src: p,
  }));
  if (order.length) {
    const rank = new Map(order.map((k, i) => [k, i] as const));
    const rankOf = (k: string) => rank.get(k) ?? Number.MAX_SAFE_INTEGER;
    models.sort((a, b) => rankOf(a.key) - rankOf(b.key));
  }
  return models;
}

export function SeasonalPricingSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: pricing, isPending } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(workspaceId!),
    enabled: !!workspaceId,
    // The editable draft re-seeds whenever the fetched config's identity changes
    // (initial load + post-save). Keep the query stable so a background refetch
    // (window refocus, remount) can't return a fresh object and silently wipe an
    // operator's unsaved edits — this editor is the only writer and updates the
    // cache directly on save.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  // Whether the workspace sells Christmas lighting at all — the quote builder
  // hides the whole service when this is off.
  const [enabled, setEnabled] = useState(false);
  const [offeringLabel, setOfferingLabel] = useState("");
  const [rooflineRate, setRooflineRate] = useState("");
  const [minimum, setMinimum] = useState("");
  const [takedownEnabled, setTakedownEnabled] = useState(false);
  // Held as a percent string; converted to/from the stored 0..1 fraction.
  const [takedownRatePct, setTakedownRatePct] = useState("");
  const [storagePrice, setStoragePrice] = useState("");
  // Season anchors for the install/takedown Service Plans (months are "1"…"12").
  const [installMonth, setInstallMonth] = useState("11");
  const [installDay, setInstallDay] = useState("15");
  const [takedownMonth, setTakedownMonth] = useState("1");
  const [takedownDay, setTakedownDay] = useState("8");
  const [categories, setCategories] = useState<EditCategory[]>([]);
  const [packagesEnabled, setPackagesEnabled] = useState(false);
  const [packages, setPackages] = useState<EditPackage[]>([]);
  // Client-visible roofline-vs-roofline cost comparison. Lives at the top level
  // of the pricing config (next to comparison_years), not inside `christmas`.
  const [rooflineComparison, setRooflineComparison] = useState(false);
  // Snapshot of the server christmas block so save preserves `perks`, the package
  // sub-fields, and anything else this editor intentionally does not expose.
  const [serverChristmas, setServerChristmas] = useState<ChristmasConfig | null>(
    null,
  );

  // Seed/re-seed the editable draft from the server config, resetting when its
  // identity changes (first load, or after a save replaces the cached copy).
  // Adjusting state during render on an identity guard is the sanctioned React
  // pattern and avoids a cascading effect render.
  if (pricing?.christmas && pricing.christmas !== serverChristmas) {
    setServerChristmas(pricing.christmas);
    setEnabled(pricing.christmas.enabled ?? false);
    setOfferingLabel(pricing.christmas.label ?? "Christmas Lighting");
    setRooflineRate(String(pricing.christmas.roofline_per_ft ?? 0));
    setMinimum(String(pricing.christmas.minimum ?? 0));
    setTakedownEnabled(pricing.christmas.takedown_enabled ?? false);
    setTakedownRatePct(rateToPercent(pricing.christmas.takedown_rate ?? 0));
    setStoragePrice(String(pricing.christmas.storage_price ?? 0));
    setInstallMonth(String(pricing.christmas.season_install_month ?? 11));
    setInstallDay(String(pricing.christmas.season_install_day ?? 15));
    setTakedownMonth(String(pricing.christmas.season_takedown_month ?? 1));
    setTakedownDay(String(pricing.christmas.season_takedown_day ?? 8));
    const cats = toEditModel(pricing.christmas.items ?? []);
    setCategories(cats);
    setPackagesEnabled(pricing.christmas.packages_enabled ?? false);
    setRooflineComparison(pricing.roofline_comparison_enabled ?? false);
    setPackages(
      toPackageEditModel(
        pricing.christmas.packages ?? [],
        cats,
        pricing.christmas.package_order ?? [],
      ),
    );
  }

  const mutation = useMutation({
    mutationFn: (update: {
      christmas: ChristmasConfig;
      roofline_comparison_enabled: boolean;
    }) => salesWizardApi.updatePricing(workspaceId!, update),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        queryKeys.salesWizard.pricing(workspaceId ?? ""),
        updated,
      );
      toast.success("Seasonal pricing saved");
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save seasonal pricing")),
  });

  const disabled = mutation.isPending || !serverChristmas;

  // ── Category / option editing ──────────────────────────────────────────
  const patchCategory = (cidKey: string, patch: Partial<EditCategory>) =>
    setCategories((prev) =>
      prev.map((c) => (c._cid === cidKey ? { ...c, ...patch } : c)),
    );

  const patchOption = (
    catCid: string,
    optCid: string,
    patch: Partial<EditOption>,
  ) =>
    setCategories((prev) =>
      prev.map((c) =>
        c._cid === catCid
          ? {
              ...c,
              options: c.options.map((o) =>
                o._cid === optCid ? { ...o, ...patch } : o,
              ),
            }
          : c,
      ),
    );

  const addCategory = () =>
    setCategories((prev) => [
      ...prev,
      {
        _cid: cid(),
        key: "",
        label: "",
        unit: "each",
        options: [{ _cid: cid(), key: "", name: "", price: 0 }],
      },
    ]);

  const removeCategory = (catCid: string) =>
    setCategories((prev) => prev.filter((c) => c._cid !== catCid));

  const addOption = (catCid: string) =>
    setCategories((prev) =>
      prev.map((c) =>
        c._cid === catCid
          ? {
              ...c,
              options: [
                ...c.options,
                { _cid: cid(), key: "", name: "", price: 0 },
              ],
            }
          : c,
      ),
    );

  const removeOption = (catCid: string, optCid: string) =>
    setCategories((prev) =>
      prev.map((c) =>
        c._cid === catCid
          ? { ...c, options: c.options.filter((o) => o._cid !== optCid) }
          : c,
      ),
    );

  // ── Package editing ───────────────────────────────────────────────────────
  const patchPackage = (pkgCid: string, patch: Partial<EditPackage>) =>
    setPackages((prev) =>
      prev.map((p) => (p._cid === pkgCid ? { ...p, ...patch } : p)),
    );

  const addPackage = () =>
    setPackages((prev) => [
      ...prev,
      {
        _cid: cid(),
        key: "",
        label: "",
        name: "",
        experience: "",
        points: "",
        includesRoofline: false,
        itemCids: [],
        src: null,
      },
    ]);

  const removePackage = (pkgCid: string) =>
    setPackages((prev) => prev.filter((p) => p._cid !== pkgCid));

  // Reorder within the low→high list; the list order becomes `package_order`.
  const movePackage = (pkgCid: string, dir: -1 | 1) =>
    setPackages((prev) => {
      const i = prev.findIndex((p) => p._cid === pkgCid);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });

  const togglePackageItem = (pkgCid: string, catCid: string, on: boolean) =>
    setPackages((prev) =>
      prev.map((p) =>
        p._cid === pkgCid
          ? {
              ...p,
              itemCids: on
                ? [...p.itemCids.filter((c) => c !== catCid), catCid]
                : p.itemCids.filter((c) => c !== catCid),
            }
          : p,
      ),
    );

  // ── Save ────────────────────────────────────────────────────────────────
  const save = () => {
    if (!serverChristmas) return;
    const offeringName = offeringLabel.trim();
    if (!offeringName) {
      toast.error("Give the offering a name");
      return;
    }
    const rate = Number.parseFloat(rooflineRate);
    const minimumValue = Number.parseFloat(minimum);
    const storageValue = Number.parseFloat(storagePrice);
    const numeric: Array<[string, number]> = [
      ["Roofline rate", rate],
      ["Job minimum", minimumValue],
      ["Storage price", storageValue],
    ];
    for (const [name, value] of numeric) {
      if (!Number.isFinite(value) || value < 0) {
        toast.error(`${name} must be a number ≥ 0`);
        return;
      }
    }
    // The operator types a percent of the install subtotal; the config stores the
    // 0..1 fraction the pricing engine multiplies by.
    const takedownPct = Number.parseFloat(takedownRatePct);
    if (!Number.isFinite(takedownPct) || takedownPct < 0 || takedownPct > 100) {
      toast.error("Takedown rate must be a percent between 0 and 100");
      return;
    }
    const takedownRate = Math.round(takedownPct * 100) / 10000;
    // Season anchors. Days are clamped as they're typed, so this only catches a
    // blank or zero day — never let the backend clamp silently rewrite a save.
    const installMonthValue = Number.parseInt(installMonth, 10);
    const takedownMonthValue = Number.parseInt(takedownMonth, 10);
    const installDayValue = Number.parseInt(installDay, 10);
    const takedownDayValue = Number.parseInt(takedownDay, 10);
    const seasonDays: Array<[string, number, number]> = [
      ["Install day", installDayValue, daysInMonth(installMonthValue)],
      ["Takedown day", takedownDayValue, daysInMonth(takedownMonthValue)],
    ];
    for (const [name, value, max] of seasonDays) {
      if (!Number.isFinite(value) || value < 1 || value > max) {
        toast.error(`${name} must be between 1 and ${max}`);
        return;
      }
    }
    // Validate + freeze keys for new rows. Pre-seed the used-key sets with every
    // existing key so a freshly-named row can never collide with one assigned
    // later in the list (keys are the stable references the pricing engine and
    // saved comparisons look selections up by).
    const usedCatKeys = new Set<string>(
      categories.map((c) => c.key).filter(Boolean),
    );
    const items: SeasonalItem[] = [];
    // Maps each category's client id to its final saved key so packages can
    // resolve their included-category selections to SeasonalItem keys below.
    const cidToKey = new Map<string, string>();
    for (const cat of categories) {
      const label = cat.label.trim();
      if (!label) {
        toast.error("Every category needs a name");
        return;
      }
      if (cat.options.length === 0) {
        toast.error(`"${label}" needs at least one option`);
        return;
      }
      const catKey = cat.key || uniqueKey(slugify(label, "category"), usedCatKeys);
      cidToKey.set(cat._cid, catKey);
      const usedOptKeys = new Set<string>(
        cat.options.map((o) => o.key).filter(Boolean),
      );
      const options = [];
      for (const opt of cat.options) {
        const name = opt.name.trim();
        if (!name) {
          toast.error(`Every option in "${label}" needs a name`);
          return;
        }
        if (!Number.isFinite(opt.price) || opt.price < 0) {
          toast.error(`"${name}" price must be a number ≥ 0`);
          return;
        }
        const optKey = opt.key || uniqueKey(slugify(name, "option"), usedOptKeys);
        options.push({ key: optKey, name, price: opt.price });
      }
      items.push({ key: catKey, label, unit: cat.unit, options });
    }

    // Freeze keys for new packages just like categories, then resolve each
    // package's included categories to their saved SeasonalItem keys.
    const usedPkgKeys = new Set<string>(
      packages.map((p) => p.key).filter(Boolean),
    );
    const builtPackages: ChristmasPackage[] = [];
    for (const pkg of packages) {
      const pkgLabel = pkg.label.trim();
      if (!pkgLabel) {
        toast.error("Every package needs a name");
        return;
      }
      const pkgKey =
        pkg.key || uniqueKey(slugify(pkgLabel, "package"), usedPkgKeys);
      const points = pkg.points
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      const itemKeys = pkg.itemCids
        .map((c) => cidToKey.get(c))
        .filter((k): k is string => Boolean(k));
      const src = pkg.src;
      builtPackages.push({
        key: pkgKey,
        label: pkgLabel,
        name: pkg.name.trim() || null,
        marker: src?.marker ?? null,
        card_tier: src?.card_tier ?? null,
        experience: pkg.experience.trim() || null,
        warranty: src?.warranty ?? null,
        points,
        value_tag: src?.value_tag ?? null,
        popular: src?.popular ?? false,
        includes_roofline: pkg.includesRoofline,
        item_keys: itemKeys,
      });
    }

    // Spread the server snapshot first so unexposed fields (perks, package
    // markers) survive the block-replace save; then apply the edited values.
    mutation.mutate({
      christmas: {
        ...serverChristmas,
        enabled,
        label: offeringName,
        roofline_per_ft: rate,
        minimum: minimumValue,
        takedown_enabled: takedownEnabled,
        takedown_rate: takedownRate,
        storage_price: storageValue,
        season_install_month: installMonthValue,
        season_install_day: installDayValue,
        season_takedown_month: takedownMonthValue,
        season_takedown_day: takedownDayValue,
        items,
        packages_enabled: packagesEnabled,
        package_order: builtPackages.map((p) => p.key),
        packages: builtPackages,
      },
      roofline_comparison_enabled: rooflineComparison,
    });
  };

  if (isPending || !serverChristmas) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1.5">
              <CardTitle>Seasonal Decor Pricing</CardTitle>
              <CardDescription>
                Add or edit seasonal add-ons — trees, bushes, wreaths, garland,
                and anything else. Choose whether each is priced per item or per
                linear foot. Turn the offering on to sell Christmas lighting at
                all — the quote builder hides the whole service while it&apos;s off.
                Changes apply instantly to the sales wizard and roofline
                estimator — no developer needed.
              </CardDescription>
            </div>
            <Switch
              checked={enabled}
              onCheckedChange={setEnabled}
              disabled={disabled}
              aria-label="Offer Christmas lighting"
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="xmas-label">Offering name</Label>
              <Input
                id="xmas-label"
                value={offeringLabel}
                onChange={(e) => setOfferingLabel(e.target.value)}
                disabled={disabled}
              />
              <p className="text-xs text-muted-foreground">
                Shown to customers on the estimate and proposal, and used to
                title the install/takedown jobs a signup schedules.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="xmas-minimum">Job minimum ($)</Label>
              <Input
                id="xmas-minimum"
                type="number"
                min={0}
                step="0.01"
                inputMode="decimal"
                value={minimum}
                onChange={(e) => setMinimum(e.target.value)}
                disabled={disabled}
              />
              <p className="text-xs text-muted-foreground">
                Floor price for any seasonal job. 0 = no minimum.
              </p>
            </div>
          </div>

          <div className="space-y-2 max-w-xs">
            <Label htmlFor="roofline-rate">Roofline rate ($ per linear ft)</Label>
            <Input
              id="roofline-rate"
              type="number"
              min={0}
              step="0.01"
              inputMode="decimal"
              value={rooflineRate}
              onChange={(e) => setRooflineRate(e.target.value)}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              The base seasonal price for the main roofline run.
            </p>
          </div>

          <Separator />

          <div className="space-y-4">
            {categories.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No decor categories yet. Add one to get started.
              </p>
            ) : null}

            {categories.map((cat) => (
              <div
                key={cat._cid}
                className="rounded-lg border p-4 space-y-4 bg-muted/20"
              >
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-2 flex-1 min-w-[180px]">
                    <Label>Category name</Label>
                    <Input
                      placeholder="e.g. Trees, Garland"
                      value={cat.label}
                      onChange={(e) =>
                        patchCategory(cat._cid, { label: e.target.value })
                      }
                      disabled={disabled}
                    />
                  </div>
                  <div className="space-y-2 w-44">
                    <Label>Priced by</Label>
                    <Select
                      value={cat.unit}
                      onValueChange={(v) =>
                        patchCategory(cat._cid, { unit: v as SeasonalUnit })
                      }
                      disabled={disabled}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="each">Per item</SelectItem>
                        <SelectItem value="per_ft">Per linear foot</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => removeCategory(cat._cid)}
                    disabled={disabled}
                    aria-label={`Remove ${cat.label || "category"}`}
                  >
                    <Trash2 className="size-4 text-destructive" />
                  </Button>
                </div>

                <div className="space-y-2">
                  {cat.options.map((opt) => (
                    <div key={opt._cid} className="flex items-end gap-3">
                      <div className="space-y-1 flex-1 min-w-[160px]">
                        <Label className="text-xs text-muted-foreground">
                          Option
                        </Label>
                        <Input
                          placeholder={
                            cat.unit === "per_ft"
                              ? "e.g. Garland (installed)"
                              : "e.g. Large tree (15–25 ft)"
                          }
                          value={opt.name}
                          onChange={(e) =>
                            patchOption(cat._cid, opt._cid, {
                              name: e.target.value,
                            })
                          }
                          disabled={disabled}
                        />
                      </div>
                      <div className="space-y-1 w-40">
                        <Label className="text-xs text-muted-foreground">
                          {cat.unit === "per_ft" ? "$ / ft" : "$ / item"}
                        </Label>
                        <Input
                          type="number"
                          min={0}
                          step="0.01"
                          inputMode="decimal"
                          value={Number.isFinite(opt.price) ? opt.price : ""}
                          onChange={(e) =>
                            patchOption(cat._cid, opt._cid, {
                              price: Number.parseFloat(e.target.value) || 0,
                            })
                          }
                          disabled={disabled}
                        />
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => removeOption(cat._cid, opt._cid)}
                        disabled={disabled || cat.options.length <= 1}
                        aria-label={`Remove ${opt.name || "option"}`}
                      >
                        <Trash2 className="size-4 text-muted-foreground" />
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => addOption(cat._cid)}
                    disabled={disabled}
                  >
                    <Plus className="size-4" /> Add option
                  </Button>
                </div>
              </div>
            ))}

            <Button
              type="button"
              variant="outline"
              onClick={addCategory}
              disabled={disabled}
            >
              <Plus className="size-4" /> Add category
            </Button>
          </div>

          <Separator />

          <div className="space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <h3 className="text-base font-semibold">Christmas Packages</h3>
                <p className="text-sm text-muted-foreground">
                  Sell seasonal lighting as ready-made tiers (Good / Better /
                  Best) instead of à la carte. Each package includes a subset of
                  the decor categories above — plus the roofline, optionally —
                  and is priced by the same engine. Order runs low → high.
                </p>
              </div>
              <Switch
                checked={packagesEnabled}
                onCheckedChange={setPackagesEnabled}
                disabled={disabled}
                aria-label="Enable Christmas packages"
              />
            </div>

            {packages.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No packages yet. Add one to get started.
              </p>
            ) : null}

            {packages.map((pkg, idx) => (
              <div
                key={pkg._cid}
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
                      onClick={() => movePackage(pkg._cid, -1)}
                      disabled={disabled || idx === 0}
                      aria-label={`Move ${pkg.label || "package"} up`}
                    >
                      <ChevronUp className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => movePackage(pkg._cid, 1)}
                      disabled={disabled || idx === packages.length - 1}
                      aria-label={`Move ${pkg.label || "package"} down`}
                    >
                      <ChevronDown className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => removePackage(pkg._cid)}
                      disabled={disabled}
                      aria-label={`Remove ${pkg.label || "package"}`}
                    >
                      <Trash2 className="size-4 text-destructive" />
                    </Button>
                  </div>
                </div>

                <div className="flex flex-wrap gap-3">
                  <div className="space-y-2 flex-1 min-w-[180px]">
                    <Label>Package label</Label>
                    <Input
                      placeholder="e.g. Premier — The Full Display"
                      value={pkg.label}
                      onChange={(e) =>
                        patchPackage(pkg._cid, { label: e.target.value })
                      }
                      disabled={disabled}
                    />
                  </div>
                  <div className="space-y-2 flex-1 min-w-[180px]">
                    <Label>Display name</Label>
                    <Input
                      placeholder="e.g. The Premier"
                      value={pkg.name}
                      onChange={(e) =>
                        patchPackage(pkg._cid, { name: e.target.value })
                      }
                      disabled={disabled}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Experience</Label>
                  <Textarea
                    rows={2}
                    placeholder="A sentence or two describing the look and feel…"
                    value={pkg.experience}
                    onChange={(e) =>
                      patchPackage(pkg._cid, { experience: e.target.value })
                    }
                    disabled={disabled}
                  />
                </div>

                <div className="space-y-2">
                  <Label>Selling points</Label>
                  <Textarea
                    rows={3}
                    placeholder={
                      "One per line, e.g.\nFull roofline outlined\nTrees and bushes wrapped"
                    }
                    value={pkg.points}
                    onChange={(e) =>
                      patchPackage(pkg._cid, { points: e.target.value })
                    }
                    disabled={disabled}
                  />
                  <p className="text-xs text-muted-foreground">
                    One bullet per line.
                  </p>
                </div>

                <div className="flex items-center justify-between gap-3">
                  <div className="space-y-0.5">
                    <Label>Include roofline</Label>
                    <p className="text-xs text-muted-foreground">
                      Adds the main roofline run to this package.
                    </p>
                  </div>
                  <Switch
                    checked={pkg.includesRoofline}
                    onCheckedChange={(v) =>
                      patchPackage(pkg._cid, { includesRoofline: v })
                    }
                    disabled={disabled}
                    aria-label={`Include roofline in ${pkg.label || "package"}`}
                  />
                </div>

                <div className="space-y-2">
                  <Label>Included decor categories</Label>
                  {categories.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      Add decor categories above to include them in a package.
                    </p>
                  ) : (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {categories.map((cat) => {
                        const cbId = `pkg-${pkg._cid}-cat-${cat._cid}`;
                        return (
                          <div
                            key={cat._cid}
                            className="flex items-center gap-2"
                          >
                            <Checkbox
                              id={cbId}
                              checked={pkg.itemCids.includes(cat._cid)}
                              onCheckedChange={(v) =>
                                togglePackageItem(
                                  pkg._cid,
                                  cat._cid,
                                  v === true,
                                )
                              }
                              disabled={disabled}
                            />
                            <Label
                              htmlFor={cbId}
                              className="text-sm font-normal"
                            >
                              {cat.label || "Untitled category"}
                            </Label>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            ))}

            <Button
              type="button"
              variant="outline"
              onClick={addPackage}
              disabled={disabled}
            >
              <Plus className="size-4" /> Add package
            </Button>
          </div>

          <Separator />

          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-base font-semibold">Takedown &amp; storage</h3>
              <p className="text-sm text-muted-foreground">
                The two post-season add-ons a client can buy alongside the
                install.
              </p>
            </div>

            <div className="flex items-start justify-between gap-4">
              <div className="space-y-0.5">
                <Label>Offer post-season takedown</Label>
                <p className="text-xs text-muted-foreground">
                  Shows the takedown option in the sales wizard. Off = you don&apos;t
                  sell takedown, and an approved quote never schedules one.
                </p>
              </div>
              <Switch
                checked={takedownEnabled}
                onCheckedChange={setTakedownEnabled}
                disabled={disabled}
                aria-label="Offer post-season takedown"
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="xmas-takedown-rate">
                  Takedown rate (% of install)
                </Label>
                <Input
                  id="xmas-takedown-rate"
                  type="number"
                  min={0}
                  max={100}
                  step="0.5"
                  inputMode="decimal"
                  value={takedownRatePct}
                  onChange={(e) => setTakedownRatePct(e.target.value)}
                  disabled={disabled}
                />
                <p className="text-xs text-muted-foreground">
                  Added on top of the install subtotal (roofline + decor) when a
                  client buys takedown. 25 = 25% of the install. If takedown is
                  already baked into your install price, set 0 and leave the
                  toggle on &mdash; the January job still needs to be on the
                  board.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="xmas-storage">Off-season storage price ($)</Label>
                <Input
                  id="xmas-storage"
                  type="number"
                  min={0}
                  step="0.01"
                  inputMode="decimal"
                  value={storagePrice}
                  onChange={(e) => setStoragePrice(e.target.value)}
                  disabled={disabled}
                />
                <p className="text-xs text-muted-foreground">
                  Flat fee to store the client&apos;s lights until next season. The
                  wizard only offers storage when this is above $0 — leave it at
                  0 if you don&apos;t store lights.
                </p>
              </div>
            </div>
          </div>

          <Separator />

          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-base font-semibold">Season dates</h3>
              <p className="text-sm text-muted-foreground">
                When the crew hangs the lights and when they come back for them.
                Approving a Christmas quote schedules two yearly Service Plans
                anchored on these days — install, plus takedown when the client
                bought it — so next season&apos;s work is already on the board. The
                year is resolved at approval, always forward from that date.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="flex items-start gap-3">
                <div className="space-y-2 flex-1">
                  <Label htmlFor="xmas-install-month">Install month</Label>
                  <Select
                    value={installMonth}
                    onValueChange={(v) => {
                      setInstallMonth(v);
                      setInstallDay((d) => clampDay(d, v));
                    }}
                    disabled={disabled}
                  >
                    <SelectTrigger
                      id="xmas-install-month"
                      aria-label="Install month"
                      className="w-full"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MONTHS.map((m) => (
                        <SelectItem key={m.value} value={m.value}>
                          {m.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2 w-24">
                  <Label htmlFor="xmas-install-day">Install day</Label>
                  <Input
                    id="xmas-install-day"
                    type="number"
                    min={1}
                    max={daysInMonth(Number.parseInt(installMonth, 10))}
                    step="1"
                    inputMode="numeric"
                    value={installDay}
                    onChange={(e) =>
                      setInstallDay(clampDay(e.target.value, installMonth))
                    }
                    disabled={disabled}
                  />
                </div>
              </div>

              <div className="flex items-start gap-3">
                <div className="space-y-2 flex-1">
                  <Label htmlFor="xmas-takedown-month">Takedown month</Label>
                  <Select
                    value={takedownMonth}
                    onValueChange={(v) => {
                      setTakedownMonth(v);
                      setTakedownDay((d) => clampDay(d, v));
                    }}
                    disabled={disabled}
                  >
                    <SelectTrigger
                      id="xmas-takedown-month"
                      aria-label="Takedown month"
                      className="w-full"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MONTHS.map((m) => (
                        <SelectItem key={m.value} value={m.value}>
                          {m.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2 w-24">
                  <Label htmlFor="xmas-takedown-day">Takedown day</Label>
                  <Input
                    id="xmas-takedown-day"
                    type="number"
                    min={1}
                    max={daysInMonth(Number.parseInt(takedownMonth, 10))}
                    step="1"
                    inputMode="numeric"
                    value={takedownDay}
                    onChange={(e) =>
                      setTakedownDay(clampDay(e.target.value, takedownMonth))
                    }
                    disabled={disabled}
                  />
                </div>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              February caps at the 28th so a yearly plan always lands on a real
              date.
            </p>
          </div>

          <Separator />

          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <h3 className="text-base font-semibold">
                Roofline cost comparison
              </h3>
              <p className="text-sm text-muted-foreground">
                Show customers a roofline-only cost comparison on every shared
                estimate: the one-time permanent install against the seasonal
                roofline they pay each year. Roofline against roofline, decor
                excluded, so the numbers are like-for-like. Only appears when
                you sell both permanent and seasonal lighting.
              </p>
            </div>
            <Switch
              checked={rooflineComparison}
              onCheckedChange={setRooflineComparison}
              disabled={disabled}
              aria-label="Show customers the roofline cost comparison"
            />
          </div>

          <Separator />

          <div className="flex justify-end">
            <Button type="button" onClick={save} disabled={disabled}>
              {mutation.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Saving…
                </>
              ) : (
                "Save seasonal pricing"
              )}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
