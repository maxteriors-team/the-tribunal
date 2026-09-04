"use client";

/** Permanent Lighting GreenSky terms and private cost settings. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import type {
  PermanentConfig,
  PermanentFinancingConfig,
  PricingSettingsUpdate,
} from "@/types/sales-wizard";

interface FormState {
  planNumber: string;
  aprPercent: string;
  termMonths: string;
  merchantFeePercent: string;
  salesCommissionPercent: string;
}

function formFrom(financing: PermanentFinancingConfig): FormState {
  const displayPercent = (rate: number) => String(Math.round(rate * 10_000) / 100);
  return {
    planNumber: financing.plan_number,
    aprPercent: displayPercent(financing.apr),
    termMonths: String(financing.term_months),
    merchantFeePercent: displayPercent(financing.merchant_fee_rate),
    salesCommissionPercent: displayPercent(financing.sales_commission_rate),
  };
}

function percentage(value: string, label: string, allowOneHundred = false): number | null {
  const parsed = Number(value);
  const maximumIsValid = allowOneHundred ? parsed <= 100 : parsed < 100;
  if (!Number.isFinite(parsed) || parsed < 0 || !maximumIsValid) {
    toast.error(`${label} must be between 0% and ${allowOneHundred ? "100%" : "less than 100%"}`);
    return null;
  }
  return parsed / 100;
}

export function FinancingSettingsCard() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const { data: pricing, isPending } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(workspaceId!),
    enabled: !!workspaceId,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const permanent = pricing?.permanent;
  const [serverPermanent, setServerPermanent] = useState<PermanentConfig | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  if (permanent?.financing && permanent !== serverPermanent) {
    setServerPermanent(permanent);
    setForm(formFrom(permanent.financing));
  }

  const mutation = useSettingsSaveMutation({
    mutationFn: (nextPermanent: PermanentConfig) =>
      salesWizardApi.updatePricing(workspaceId!, {
        permanent: nextPermanent,
      } as PricingSettingsUpdate),
    successMessage: "Permanent Lighting financing settings are up to date.",
    errorMessage: "We couldn't save GreenSky settings. Check your connection and try again.",
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.salesWizard.pricing(workspaceId ?? ""), updated);
    },
  });

  const disabled = mutation.isPending || !serverPermanent || !form;
  const patch = (field: keyof FormState, value: string) =>
    setForm((current) => (current ? { ...current, [field]: value } : current));

  const save = () => {
    if (!serverPermanent || !form) return;
    const planNumber = form.planNumber.trim();
    if (!/^\d{1,32}$/.test(planNumber)) {
      toast.error("Plan number must contain 1–32 digits");
      return;
    }
    const termMonths = Number(form.termMonths);
    if (!Number.isInteger(termMonths) || termMonths < 1 || termMonths > 360) {
      toast.error("Financing term must be a whole number from 1 to 360 months");
      return;
    }
    const apr = percentage(form.aprPercent, "APR", true);
    const merchantFeeRate = percentage(form.merchantFeePercent, "Merchant fee");
    const salesCommissionRate = percentage(form.salesCommissionPercent, "Sales commission");
    if (apr === null || merchantFeeRate === null || salesCommissionRate === null) return;

    mutation.mutate({
      ...serverPermanent,
      financing: {
        provider: "GreenSky",
        plan_number: planNumber,
        apr,
        term_months: termMonths,
        merchant_fee_rate: merchantFeeRate,
        sales_commission_rate: salesCommissionRate,
      },
    });
  };

  if (isPending || !form) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="size-6 animate-spin text-muted-foreground" aria-label="Loading" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Permanent Lighting — GreenSky</CardTitle>
        <CardDescription>
          These terms appear only on exact Permanent Lighting proposals. Cash/check and GreenSky
          always use the same customer price.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="greensky-plan">Plan number</Label>
            <Input
              id="greensky-plan"
              inputMode="numeric"
              value={form.planNumber}
              onChange={(event) => patch("planNumber", event.target.value)}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="greensky-term">Financing term (months)</Label>
            <Input
              id="greensky-term"
              type="number"
              min={1}
              max={360}
              step={1}
              value={form.termMonths}
              onChange={(event) => patch("termMonths", event.target.value)}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="greensky-apr">APR (%)</Label>
            <Input
              id="greensky-apr"
              type="number"
              min={0}
              max={100}
              step="0.01"
              inputMode="decimal"
              value={form.aprPercent}
              onChange={(event) => patch("aprPercent", event.target.value)}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="greensky-fee">Merchant fee (%)</Label>
            <Input
              id="greensky-fee"
              type="number"
              min={0}
              max="99.99"
              step="0.01"
              inputMode="decimal"
              value={form.merchantFeePercent}
              onChange={(event) => patch("merchantFeePercent", event.target.value)}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="greensky-commission">Sales commission (%)</Label>
            <Input
              id="greensky-commission"
              type="number"
              min={0}
              max="99.99"
              step="0.01"
              inputMode="decimal"
              value={form.salesCommissionPercent}
              onChange={(event) => patch("salesCommissionPercent", event.target.value)}
              disabled={disabled}
            />
          </div>
        </div>

        <div className="rounded-lg border bg-muted/40 p-4 text-sm">
          <p className="font-medium">The GreenSky merchant fee is a company cost.</p>
          <p className="mt-1 text-muted-foreground">
            It reduces contribution on financed jobs and never increases the customer&rsquo;s price.
          </p>
        </div>

        <div className="flex justify-end">
          <Button className="w-full sm:w-auto" type="button" onClick={save} disabled={disabled}>
            {mutation.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Saving…
              </>
            ) : (
              "Save GreenSky settings"
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
