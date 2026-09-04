"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { quotesApi } from "@/lib/api/quotes";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { PermanentProfitabilityScenario, Quote } from "@/types";

interface PermanentProfitabilityDialogProps {
  quote: Quote | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function percent(rate: number): string {
  return `${(rate * 100).toFixed(2).replace(/\.00$/, "")}%`;
}

function ScenarioCard({
  title,
  scenario,
  currency,
  selected,
}: {
  title: string;
  scenario: PermanentProfitabilityScenario;
  currency: string;
  selected: boolean;
}) {
  const money = (amount: number) => formatCurrency(amount, currency);
  return (
    <section
      className={`rounded-lg border p-4 ${selected ? "border-primary bg-primary/5" : ""}`}
      aria-label={`${title} profitability`}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="font-semibold">{title}</h3>
        {selected ? <Badge>Contracted</Badge> : null}
      </div>
      <dl className="space-y-2 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Customer price</dt>
          <dd className="font-medium">{money(scenario.contract_price)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">
            Merchant fee ({percent(scenario.merchant_fee_rate)})
          </dt>
          <dd>{money(scenario.merchant_fee)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">
            Sales commission ({percent(scenario.sales_commission_rate)})
          </dt>
          <dd>{money(scenario.sales_commission)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Package Material COGS</dt>
          <dd>{money(scenario.material_cogs)}</dd>
        </div>
        <div className="mt-3 flex justify-between gap-4 border-t pt-3">
          <dt className="font-semibold">Contribution Before Labor</dt>
          <dd className="font-semibold">{money(scenario.contribution_before_labor)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Contribution margin</dt>
          <dd>{percent(scenario.contribution_margin)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function PermanentProfitabilityDialog({
  quote,
  open,
  onOpenChange,
}: PermanentProfitabilityDialogProps) {
  const workspaceId = useWorkspaceId();
  const query = useQuery({
    queryKey: queryKeys.quotes.permanentProfitability(workspaceId ?? "", quote?.id ?? ""),
    queryFn: () => quotesApi.permanentProfitability(workspaceId!, quote!.id),
    enabled: open && Boolean(workspaceId && quote),
    staleTime: 30_000,
  });
  const data = query.data;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Permanent Lighting Profitability</DialogTitle>
          <DialogDescription>
            Private company economics for quote {quote?.number}. Labor is not included.
          </DialogDescription>
        </DialogHeader>

        {query.isPending ? (
          <div className="flex min-h-40 items-center justify-center" role="status">
            <Loader2 className="size-6 animate-spin" aria-hidden="true" />
            <span className="sr-only">Loading profitability</span>
          </div>
        ) : query.isError ? (
          <p className="rounded-md border border-destructive/40 p-4 text-sm text-destructive">
            {getApiErrorMessage(query.error, "Could not load profitability")}
          </p>
        ) : !data ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Profitability is unavailable for this quote.
          </p>
        ) : (
          <div className="space-y-5">
            <dl className="grid gap-3 rounded-lg bg-muted/50 p-4 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Financing provider</dt>
                <dd className="font-medium">
                  {data.provider} plan {data.plan_number}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Terms</dt>
                <dd className="font-medium">
                  {percent(data.apr)} APR · {data.term_months} months
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Estimated payment</dt>
                <dd className="font-medium">
                  Approximately{" "}
                  {formatCurrency(Math.round(data.estimated_monthly_payment), data.currency)}
                  /month
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Customer price policy</dt>
                <dd className="font-medium">Same price for both methods</dd>
              </div>
            </dl>

            <div className="grid gap-4 md:grid-cols-2">
              <ScenarioCard
                title="Cash/Check"
                scenario={data.cash_check}
                currency={data.currency}
                selected={data.selected_payment_option === "cash_check"}
              />
              <ScenarioCard
                title="GreenSky Financing"
                scenario={data.financing}
                currency={data.currency}
                selected={data.selected_payment_option === "financing"}
              />
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
