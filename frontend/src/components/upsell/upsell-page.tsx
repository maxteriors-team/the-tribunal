"use client";

/**
 * On-site upsell — the technician's driveway sales flow.
 *
 * Two steps, one action each: pick the house, then build the receipt and send
 * it. Design read, thesis, and state plan live in `./DESIGN.md`.
 *
 * The screen is deliberately thin. Every price and every scoping rule is
 * resolved by the server (`/api/v1/workspaces/{id}/upsell/*`), so this component
 * sends catalog ids and quantities and never computes anything the customer will
 * be billed for. The running total here is a preview of the server's arithmetic,
 * and the created quote's own total is what is displayed once it exists.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarClock,
  Check,
  ChevronRight,
  MapPin,
  PackageOpen,
  Send,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { UpsellAddonRow } from "@/components/upsell/upsell-addon-row";
import { UpsellCarePlanSection } from "@/components/upsell/upsell-care-plan";
import { UpsellSummaryBar } from "@/components/upsell/upsell-summary-bar";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { upsellApi, type UpsellJob, type UpsellQuote } from "@/lib/api/upsell";
import { queryKeys } from "@/lib/query-keys";
import { STATIC } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import { formatPhoneNumber } from "@/lib/utils/phone";

/** Shared content rail: header, list, and the summary bar's inner content. */
const RAIL = "mx-auto w-full max-w-screen-sm px-4";

function formatWhen(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function UpsellPage() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const [activeJob, setActiveJob] = useState<UpsellJob | null>(null);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [createdQuote, setCreatedQuote] = useState<UpsellQuote | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sent, setSent] = useState(false);
  // Care Plan state. The fixture count is a pricing input, so it lives here and
  // drives the query key rather than being posted blind with the proposal.
  const [fixtureCount, setFixtureCount] = useState(0);
  const [carePlanKey, setCarePlanKey] = useState<string | null>(null);

  const jobsQuery = useQuery({
    queryKey: queryKeys.upsell.jobs(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return upsellApi.listJobs(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const customerQuery = useQuery({
    queryKey: queryKeys.upsell.customer(workspaceId ?? "", activeJob?.id ?? ""),
    queryFn: () => {
      if (!workspaceId || !activeJob) throw new Error("No job");
      return upsellApi.getCustomer(workspaceId, activeJob.id);
    },
    enabled: !!workspaceId && !!activeJob,
  });

  const catalogQuery = useQuery({
    queryKey: queryKeys.upsell.catalog(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return upsellApi.listCatalog(workspaceId);
    },
    enabled: !!workspaceId && !!activeJob,
    ...STATIC,
  });

  const carePlanQuery = useQuery({
    queryKey: queryKeys.upsell.carePlans(workspaceId ?? "", fixtureCount),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return upsellApi.listCarePlans(workspaceId, fixtureCount);
    },
    enabled: !!workspaceId && !!activeJob,
    // Keep the previous prices on screen while a new count is priced, so the
    // tier list does not blank out under the technician's thumb mid-count.
    placeholderData: (previous) => previous,
  });

  const createQuote = useMutation({
    mutationFn: () => {
      if (!workspaceId || !activeJob) throw new Error("No job");
      return upsellApi.createQuote(workspaceId, activeJob.id, {
        line_items: Object.entries(quantities)
          .filter(([, qty]) => qty > 0)
          .map(([catalog_item_id, quantity]) => ({ catalog_item_id, quantity })),
        care_plan: carePlanKey
          ? { tier_key: carePlanKey, fixture_count: fixtureCount }
          : null,
      });
    },
    onSuccess: (quote) => {
      setCreatedQuote(quote);
      // The new draft belongs to the workspace's quote list too.
      void queryClient.invalidateQueries({ queryKey: queryKeys.quotes.root() });
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "We couldn't build that proposal."));
    },
  });

  const deliverQuote = useMutation({
    mutationFn: (channel: "sms" | "email") => {
      if (!workspaceId || !activeJob || !createdQuote) throw new Error("No quote");
      return upsellApi.deliverQuote(workspaceId, activeJob.id, createdQuote.id, {
        channel,
      });
    },
    onSuccess: () => {
      setConfirmOpen(false);
      setSent(true);
      toast.success("Proposal sent.");
    },
    onError: (error) => {
      // Keep the dialog open and the draft intact: the tech can retry the other
      // rail (or hand the customer the price verbally) without rebuilding.
      toast.error(getApiErrorMessage(error, "We couldn't send that proposal."));
    },
  });

  const catalogItems = useMemo(() => catalogQuery.data?.items ?? [], [catalogQuery.data]);

  const { selectedCount, previewTotal } = useMemo(() => {
    let count = 0;
    let total = 0;
    for (const item of catalogItems) {
      const qty = quantities[item.id] ?? 0;
      if (qty > 0) {
        count += 1;
        total += qty * item.unit_price;
      }
    }
    return { selectedCount: count, previewTotal: total };
  }, [catalogItems, quantities]);

  const resetToJobs = () => {
    setActiveJob(null);
    setQuantities({});
    setCreatedQuote(null);
    setSent(false);
    setFixtureCount(0);
    setCarePlanKey(null);
  };

  const carePlanOptions = carePlanQuery.data?.options ?? [];
  const selectedCarePlan =
    carePlanOptions.find((option) => option.key === carePlanKey) ?? null;
  // The plan a *created* quote carries comes from its frozen snapshot, not from
  // local state: once the server has priced it, the server's number is the one
  // the customer will see.
  const quotedCarePlan = createdQuote
    ? ((createdQuote.proposal_document?.care_plan ?? null) as {
        selected?: string | null;
        options?: { key: string; name: string; price: number }[];
      } | null)
    : null;
  const quotedCarePlanOption =
    quotedCarePlan?.options?.find((option) => option.key === quotedCarePlan.selected) ?? null;
  const recurringTotal = createdQuote
    ? (quotedCarePlanOption?.price ?? 0)
    : (selectedCarePlan?.price ?? 0);
  const nothingSelected = selectedCount === 0 && !carePlanKey;

  // ---------------------------------------------------------------- step 1
  if (!activeJob) {
    return (
      <div className="flex min-h-full flex-col">
        <header className={`${RAIL} pt-6 pb-4`}>
          <h1 className="text-2xl font-semibold tracking-tight">Sell an add-on</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Pick the house you are at.
          </p>
        </header>

        <div className={`${RAIL} flex-1 pb-6`}>
          {jobsQuery.isPending ? (
            <PageLoadingState message="Loading your jobs…" />
          ) : jobsQuery.isError ? (
            <PageErrorState
              message="We couldn't load your jobs."
              onRetry={() => void jobsQuery.refetch()}
            />
          ) : jobsQuery.data.items.length === 0 ? (
            <PageEmptyState
              icon={<CalendarClock className="size-8" />}
              title="No jobs assigned to you"
              description="Add-ons are sold from a job you are on. Ask your dispatcher to assign you one."
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {jobsQuery.data.items.map((job) => {
                const when = formatWhen(job.scheduled_start);
                return (
                  <li key={job.id}>
                    <button
                      type="button"
                      onClick={() => setActiveJob(job)}
                      className="flex min-h-16 w-full items-center gap-3 rounded-lg border bg-card p-4 text-left outline-none transition-[border-color,background-color] duration-150 hover:border-primary/50 hover:bg-accent/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 motion-reduce:transition-none"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">
                          {job.title}
                        </span>
                        {when ? (
                          <span className="mt-0.5 block text-sm text-muted-foreground">
                            {when}
                          </span>
                        ) : null}
                      </span>
                      <ChevronRight
                        className="size-5 shrink-0 text-muted-foreground"
                        aria-hidden="true"
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- sent
  if (sent && createdQuote) {
    return (
      <div className={`${RAIL} flex min-h-full flex-col justify-center py-10`}>
        <PageEmptyState
          icon={<Check className="size-8 text-primary" />}
          title="Proposal sent"
          description={`${customerQuery.data?.full_name ?? "The customer"} can approve it from their phone. You'll see it in the pipeline either way.`}
          action={
            <Button variant="outline" onClick={resetToJobs}>
              Sell another add-on
            </Button>
          }
        />
      </div>
    );
  }

  // ---------------------------------------------------------------- step 2
  const customer = customerQuery.data;
  const addressLine = [customer?.address_line1, customer?.address_city]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="flex min-h-full flex-col">
      <header className={`${RAIL} pt-4 pb-3`}>
        <Button
          variant="ghost"
          size="sm"
          onClick={resetToJobs}
          className="-ml-2 mb-2"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          All jobs
        </Button>

        {customerQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Loading customer…</p>
        ) : customerQuery.isError ? (
          <PageErrorState
            className="min-h-0 p-0 text-left"
            message="We couldn't load this customer."
            onRetry={() => void customerQuery.refetch()}
          />
        ) : (
          <>
            <h1 className="text-2xl font-semibold tracking-tight">
              {customer?.full_name}
            </h1>
            <div className="mt-1 flex flex-col gap-0.5 text-sm text-muted-foreground">
              {addressLine ? (
                <span className="flex items-center gap-1.5">
                  <MapPin className="size-3.5 shrink-0" aria-hidden="true" />
                  {addressLine}
                </span>
              ) : null}
              <span>{activeJob.title}</span>
            </div>
          </>
        )}
      </header>

      <div className={`${RAIL} flex-1 pb-4`}>
        {createdQuote ? (
          <section
            aria-labelledby="upsell-draft-heading"
            className="rounded-lg border bg-card p-4"
          >
            <h2 id="upsell-draft-heading" className="font-medium">
              Proposal {createdQuote.number} is ready
            </h2>

            <p className="mt-1 text-sm text-muted-foreground">
              Send it to {customer?.full_name ?? "the customer"} at{" "}
              {formatPhoneNumber(customer?.phone_number)}.
            </p>
            <ul className="mt-3 flex flex-col gap-1 border-t pt-3 text-sm">
              {(createdQuote.line_items ?? []).map((line) => (
                <li key={line.id} className="flex justify-between gap-4">
                  <span className="min-w-0 truncate">
                    {line.quantity > 1 ? `${line.quantity} × ` : ""}
                    {line.name}
                  </span>
                  <span className="shrink-0 tabular-nums">
                    {formatCurrency(line.total)}
                  </span>
                </li>
              ))}
              {quotedCarePlanOption ? (
                <li className="flex justify-between gap-4 border-t pt-2">
                  <span className="min-w-0 truncate">
                    {quotedCarePlanOption.name} care plan
                  </span>
                  <span className="shrink-0 tabular-nums">
                    {formatCurrency(quotedCarePlanOption.price)}/yr
                  </span>
                </li>
              ) : null}
            </ul>
            {/* "Edit" lives with the proposal it edits rather than in the summary
                bar: the bar carries exactly one action so the total never has to
                compete with a second control for width on a small phone. */}
            <Button
              variant="outline"
              className="mt-3 min-h-11 w-full"
              onClick={() => {
                setCreatedQuote(null);
                createQuote.reset();
              }}
            >
              Edit selection
            </Button>
          </section>
        ) : catalogQuery.isPending ? (
          <PageLoadingState message="Loading add-ons…" />
        ) : catalogQuery.isError ? (
          <PageErrorState
            message="We couldn't load the add-on menu."
            onRetry={() => void catalogQuery.refetch()}
          />
        ) : catalogItems.length === 0 ? (
          <PageEmptyState
            icon={<PackageOpen className="size-8" />}
            title="No add-ons set up yet"
            description="Ask your manager to mark price-book items as add-ons so they show up here."
          />
        ) : (
          <>
            <h2 className="sr-only">Add-ons</h2>
            <ul className="flex flex-col gap-2">

              {catalogItems.map((item) => {
                const quantity = quantities[item.id] ?? 0;
                return (
                  <UpsellAddonRow
                    key={item.id}
                    item={item}
                    quantity={quantity}
                    disabled={createQuote.isPending}
                    onToggle={() =>
                      setQuantities((prev) => ({
                        ...prev,
                        [item.id]: quantity > 0 ? 0 : 1,
                      }))
                    }
                    onQuantityChange={(next) =>
                      setQuantities((prev) => ({
                        ...prev,
                        [item.id]: Math.max(0, Math.min(99, next)),
                      }))
                    }
                  />
                );
              })}
            </ul>
            <UpsellCarePlanSection
              options={carePlanOptions}
              freeFixtures={carePlanQuery.data?.free_fixtures ?? 0}
              fixtureCount={fixtureCount}
              selectedKey={carePlanKey}
              disabled={createQuote.isPending}
              onFixtureCountChange={setFixtureCount}
              onSelect={setCarePlanKey}
            />
          </>
        )}
      </div>

      <UpsellSummaryBar
        itemCount={
          createdQuote ? (createdQuote.line_items ?? []).length : selectedCount
        }
        total={createdQuote ? createdQuote.total : previewTotal}
        recurringTotal={recurringTotal}
        actionLabel={createdQuote ? "Send to customer" : "Build proposal"}
        pendingLabel={createdQuote ? "Sending…" : "Building…"}
        pending={createQuote.isPending}
        disabled={createdQuote ? false : nothingSelected}
        onAction={() => {
          if (createdQuote) {
            setConfirmOpen(true);
          } else {
            createQuote.mutate();
          }
        }}
      />

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send this proposal?</DialogTitle>
            <DialogDescription>
              {customer?.full_name ?? "The customer"} gets a text at{" "}
              {formatPhoneNumber(customer?.phone_number)} with a link to approve
              {createdQuote && createdQuote.total > 0
                ? ` ${formatCurrency(createdQuote.total)} of work`
                : ""}
              {createdQuote && createdQuote.total > 0 && quotedCarePlanOption
                ? " plus"
                : ""}
              {/* Named as a subscription, never merged into the one-time figure:
                  this dialog is the last thing shown before a real customer is
                  billed, so it must not overstate or understate either number. */}
              {quotedCarePlanOption
                ? ` the ${quotedCarePlanOption.name} care plan at ${formatCurrency(
                    quotedCarePlanOption.price,
                  )} a year`
                : ""}
              .
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={deliverQuote.isPending}
            >
              Not yet
            </Button>
            <Button
              onClick={() => deliverQuote.mutate("sms")}
              disabled={deliverQuote.isPending}
            >
              <Send className="size-4" aria-hidden="true" />
              {deliverQuote.isPending ? "Sending…" : "Send text"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
