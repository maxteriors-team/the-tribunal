"use client";

/**
 * Settings → Pricing: the seasonal-decor editor (operator self-serve).
 *
 * Lets a non-technical operator add, edit, reorder-free, and remove seasonal
 * decor categories (trees, bushes, wreaths, garland, and anything new) plus the
 * roofline base rate — the exact `christmas.items` catalog the sales wizard and
 * roofline estimator render from. Saving PUTs the whole `christmas` block back
 * (the endpoint replaces blocks wholesale), so every other pricing field is
 * preserved. No code change or deploy needed to add a new add-on.
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

  const [rooflineRate, setRooflineRate] = useState("");
  const [categories, setCategories] = useState<EditCategory[]>([]);
  const [packagesEnabled, setPackagesEnabled] = useState(false);
  const [packages, setPackages] = useState<EditPackage[]>([]);
  // Snapshot of the server christmas block so save preserves takedown/storage/
  // perks/etc. that this editor intentionally does not expose.
  const [serverChristmas, setServerChristmas] = useState<ChristmasConfig | null>(
    null,
  );

  // Seed/re-seed the editable draft from the server config, resetting when its
  // identity changes (first load, or after a save replaces the cached copy).
  // Adjusting state during render on an identity guard is the sanctioned React
  // pattern and avoids a cascading effect render.
  if (pricing?.christmas && pricing.christmas !== serverChristmas) {
    setServerChristmas(pricing.christmas);
    setRooflineRate(String(pricing.christmas.roofline_per_ft ?? 0));
    const cats = toEditModel(pricing.christmas.items ?? []);
    setCategories(cats);
    setPackagesEnabled(pricing.christmas.packages_enabled ?? false);
    setPackages(
      toPackageEditModel(
        pricing.christmas.packages ?? [],
        cats,
        pricing.christmas.package_order ?? [],
      ),
    );
  }

  const mutation = useMutation({
    mutationFn: (christmas: ChristmasConfig) =>
      salesWizardApi.updatePricing(workspaceId!, { christmas }),
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
    const rate = Number.parseFloat(rooflineRate);
    if (!Number.isFinite(rate) || rate < 0) {
      toast.error("Roofline rate must be a number ≥ 0");
      return;
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

    mutation.mutate({
      ...serverChristmas,
      roofline_per_ft: rate,
      items,
      packages_enabled: packagesEnabled,
      package_order: builtPackages.map((p) => p.key),
      packages: builtPackages,
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
          <CardTitle>Seasonal Decor Pricing</CardTitle>
          <CardDescription>
            Add or edit seasonal add-ons — trees, bushes, wreaths, garland, and
            anything else. Choose whether each is priced per item or per linear
            foot. Changes apply instantly to the sales wizard and roofline
            estimator — no developer needed.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
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
