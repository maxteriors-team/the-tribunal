"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  CampaignPicker,
  LeadSourcePicker,
} from "@/components/lead-sources/source-pickers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  leadSourcesApi,
  type LeadSourceSpendEntry,
  type LeadSourceSpendEntryCreateRequest,
} from "@/lib/api/lead-sources";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface ManualSpendFormProps {
  workspaceId: string;
  onCreated?: (entry: LeadSourceSpendEntry) => void;
}

/** Manual ad/source spend entry: spend a source over a date range. */
export function ManualSpendForm({ workspaceId, onCreated }: ManualSpendFormProps) {
  const queryClient = useQueryClient();
  const [leadSourceId, setLeadSourceId] = useState<string>();
  const [campaignId, setCampaignId] = useState<string>();
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [notes, setNotes] = useState("");

  const amountValue = Number(amount);
  const amountValid = amount.trim() !== "" && Number.isFinite(amountValue) && amountValue >= 0;
  const datesPresent = startsOn !== "" && endsOn !== "";
  const dateRangeValid = !datesPresent || endsOn >= startsOn;

  const canSubmit =
    !!leadSourceId && amountValid && datesPresent && dateRangeValid;

  const createMutation = useMutation({
    mutationFn: (data: LeadSourceSpendEntryCreateRequest) =>
      leadSourcesApi.createSpend(workspaceId, data),
    onSuccess: (entry) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.leadSources.spend(workspaceId),
      });
      toast.success("Spend recorded");
      setAmount("");
      setNotes("");
      setCampaignId(undefined);
      onCreated?.(entry);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to record spend")),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !leadSourceId) return;
    createMutation.mutate({
      lead_source_id: leadSourceId,
      lead_source_campaign_id: campaignId ?? null,
      spend_starts_on: startsOn,
      spend_ends_on: endsOn,
      amount: amountValue,
      currency: currency.trim().toUpperCase() || "USD",
      notes: notes.trim() || null,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" aria-label="Manual spend entry">
      <div className="space-y-2">
        <Label htmlFor="spend-source">Lead source</Label>
        <LeadSourcePicker
          id="spend-source"
          workspaceId={workspaceId}
          value={leadSourceId}
          onChange={(id) => {
            setLeadSourceId(id);
            setCampaignId(undefined);
          }}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="spend-campaign">Campaign (optional)</Label>
        <CampaignPicker
          id="spend-campaign"
          workspaceId={workspaceId}
          leadSourceId={leadSourceId}
          value={campaignId}
          onChange={setCampaignId}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="spend-amount">Amount</Label>
          <Input
            id="spend-amount"
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            placeholder="0.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            aria-invalid={amount !== "" && !amountValid}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="spend-currency">Currency</Label>
          <Input
            id="spend-currency"
            maxLength={3}
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="spend-start">Start date</Label>
          <Input
            id="spend-start"
            type="date"
            value={startsOn}
            onChange={(e) => setStartsOn(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="spend-end">End date</Label>
          <Input
            id="spend-end"
            type="date"
            value={endsOn}
            onChange={(e) => setEndsOn(e.target.value)}
            aria-invalid={datesPresent && !dateRangeValid}
          />
        </div>
      </div>

      {datesPresent && !dateRangeValid && (
        <p className="text-sm text-destructive" role="alert">
          End date must be on or after the start date.
        </p>
      )}

      <div className="space-y-2">
        <Label htmlFor="spend-notes">Notes (optional)</Label>
        <Textarea
          id="spend-notes"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>

      <Button type="submit" disabled={!canSubmit || createMutation.isPending}>
        {createMutation.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
        Record spend
      </Button>
    </form>
  );
}
