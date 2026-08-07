"use client";

/**
 * Settings → Pricing: what field technicians may sell, and what they earn for it.
 *
 * Two knobs on one card because they are the same policy read from both ends:
 * the limit says how much a technician may sell on their own, and the ladder
 * says what they get for selling more.
 *
 * **This card sets targets and prints labels; it never pays anyone.** `reward`
 * is free text shown to the technician on their scoreboard — payroll stays
 * wherever payroll already is. Saying so on the card matters, because a field
 * named "reward" next to a dollar figure invites the assumption that ticking it
 * causes money to move.
 *
 * Saving PUTs the whole `upsell` block back (the endpoint replaces blocks
 * wholesale), so a field this editor doesn't expose round-trips untouched.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
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
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { UpsellConfig, UpsellRankConfig } from "@/types/sales-wizard";

// One editable rank. Numbers are held as strings so a half-typed threshold never
// snaps to 0 mid-edit; they're parsed and validated on save.
interface RankRow {
  /** Stable across renders so React keys survive typing in the name field. */
  id: string;
  key: string;
  name: string;
  threshold: string;
  reward: string;
}

let rowSeq = 0;
const nextRowId = () => `rank-row-${(rowSeq += 1)}`;

function toRows(ranks: UpsellRankConfig[] | null | undefined): RankRow[] {
  return (ranks ?? []).map((rank) => ({
    id: nextRowId(),
    key: rank.key,
    name: rank.name,
    threshold: String(rank.threshold ?? 0),
    reward: rank.reward ?? "",
  }));
}

/** Derive a stable slug for a new rank so operators never type a key by hand. */
function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40);
}

export function UpsellRanksSettingsCard() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: pricing, isPending } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(workspaceId!),
    enabled: !!workspaceId,
    // Shared with the other pricing editors by key (React Query dedupes the
    // fetch). Kept stable so a background refetch can't wipe unsaved edits.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const [rows, setRows] = useState<RankRow[] | null>(null);
  const [limit, setLimit] = useState("");
  const [serverUpsell, setServerUpsell] = useState<UpsellConfig | null>(null);

  if (pricing?.upsell && pricing.upsell !== serverUpsell) {
    setServerUpsell(pricing.upsell);
    setRows(toRows(pricing.upsell.ranks));
    setLimit(
      pricing.upsell.field_proposal_limit === null ||
        pricing.upsell.field_proposal_limit === undefined
        ? ""
        : String(pricing.upsell.field_proposal_limit),
    );
  }

  const mutation = useMutation({
    mutationFn: (upsell: UpsellConfig) =>
      salesWizardApi.updatePricing(workspaceId!, { upsell }),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        queryKeys.salesWizard.pricing(workspaceId ?? ""),
        updated,
      );
      toast.success("Field selling settings saved");
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save field selling settings")),
  });

  const disabled = mutation.isPending || !serverUpsell || !rows;

  const patchRow = (id: string, patch: Partial<RankRow>) =>
    setRows((prev) =>
      prev ? prev.map((row) => (row.id === id ? { ...row, ...patch } : row)) : prev,
    );

  const addRow = () =>
    setRows((prev) => [
      ...(prev ?? []),
      { id: nextRowId(), key: "", name: "", threshold: "0", reward: "" },
    ]);

  const removeRow = (id: string) =>
    setRows((prev) => (prev ? prev.filter((row) => row.id !== id) : prev));

  const save = () => {
    if (!serverUpsell || !rows) return;

    // Blank means no cap, which is what the backend treats null as. An empty
    // field must not save as 0 — that would silently stop every technician from
    // selling anything at all.
    let fieldLimit: number | null = null;
    if (limit.trim()) {
      const parsed = Number.parseFloat(limit);
      if (!Number.isFinite(parsed) || parsed < 0) {
        toast.error("On-site limit must be a number ≥ 0, or blank for no limit");
        return;
      }
      fieldLimit = parsed;
    }

    const ranks: UpsellRankConfig[] = [];
    const seen = new Set<string>();
    for (const row of rows) {
      const name = row.name.trim();
      if (!name) {
        toast.error("Give every rank a name, or remove the empty row");
        return;
      }
      const threshold = Number.parseFloat(row.threshold);
      if (!Number.isFinite(threshold) || threshold < 0) {
        toast.error(`Target for "${name}" must be a number ≥ 0`);
        return;
      }
      // Keys are what a saved rank is identified by; a collision would make two
      // rungs indistinguishable on the technician's scoreboard.
      const key = row.key.trim() || slugify(name);
      if (!key) {
        toast.error(`"${name}" needs at least one letter or number`);
        return;
      }
      if (seen.has(key)) {
        toast.error(`Two ranks are both called "${name}"`);
        return;
      }
      seen.add(key);
      ranks.push({
        key,
        name,
        threshold,
        reward: row.reward.trim() || null,
      });
    }

    // Spread the server snapshot first so any field this editor doesn't expose
    // survives the block-replace save. The backend sorts ranks by threshold, so
    // rows may be entered in any order.
    mutation.mutate({
      ...serverUpsell,
      field_proposal_limit: fieldLimit,
      ranks,
    });
  };

  if (isPending || !rows) {
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
        <div className="space-y-1.5">
          <CardTitle>Field Selling</CardTitle>
          <CardDescription>
            What technicians can sell from a job site, and the targets they see on
            their own scoreboard. Lead technicians are never limited.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="upsell-field-limit">Technician on-site limit ($)</Label>
          <Input
            id="upsell-field-limit"
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            className="w-48"
            placeholder="No limit"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            disabled={disabled}
          />
          <p className="text-xs text-muted-foreground">
            The most a Technician can put on one proposal without help. Leave
            blank for no limit. Care plans don&rsquo;t count toward it, and Lead
            Technicians are exempt.
          </p>
        </div>

        <Separator />

        <div className="space-y-3">
          <div className="space-y-1">
            <h3 className="text-sm font-medium">Bonus ranks</h3>
            <p className="text-xs text-muted-foreground">
              Ranks a technician climbs by approved upsell revenue each month.
              Leave empty for no ranks — they&rsquo;ll still see what they sold.
            </p>
          </div>

          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No ranks yet. Add one to give technicians a target.
            </p>
          ) : (
            <div className="flex items-end gap-3 text-sm font-medium">
              <div className="flex-1">Rank name</div>
              <div className="w-32">Target ($)</div>
              <div className="flex-1">Bonus</div>
              {/* Spacer matching the per-row remove button. */}
              <div className="size-9" aria-hidden="true" />
            </div>
          )}

          {rows.map((row, index) => (
            <div key={row.id} className="flex items-end gap-3">
              <Input
                className="flex-1"
                aria-label={`Rank ${index + 1} name`}
                value={row.name}
                placeholder="Gold"
                onChange={(e) => patchRow(row.id, { name: e.target.value })}
                disabled={disabled}
              />
              <Input
                className="w-32"
                aria-label={`Rank ${index + 1} target ($)`}
                type="number"
                min={0}
                step="0.01"
                inputMode="decimal"
                value={row.threshold}
                onChange={(e) => patchRow(row.id, { threshold: e.target.value })}
                disabled={disabled}
              />
              <Input
                className="flex-1"
                aria-label={`Rank ${index + 1} bonus`}
                value={row.reward}
                placeholder="$500 bonus"
                onChange={(e) => patchRow(row.id, { reward: e.target.value })}
                disabled={disabled}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove rank ${index + 1}`}
                onClick={() => removeRow(row.id)}
                disabled={disabled}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addRow}
            disabled={disabled}
          >
            <Plus className="size-4" /> Add rank
          </Button>
          <p className="text-xs text-muted-foreground">
            Bonus text is shown to the technician as-is — it doesn&rsquo;t pay
            anything, so keep paying it however you do today. Order doesn&rsquo;t
            matter; ranks sort by target.
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
              "Save field selling settings"
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
