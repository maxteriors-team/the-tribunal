"use client";

/**
 * On-site upsell — the technician's driveway sales flow.
 *
 * Two steps: pick the current job, then build the receipt and either present it
 * in person or send it. Design read, thesis, and state plan live in `./DESIGN.md`.
 *
 * The screen is deliberately thin. Every price and every scoping rule is
 * resolved by the server (`/api/v1/workspaces/{id}/upsell/*`). Catalog lines send
 * only ids and quantities; custom lines are the bounded, server-capped exception.
 * The running total here is a preview of the server's arithmetic, and the created
 * quote's own total is what is displayed once it exists.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarClock,
  Check,
  ChevronRight,
  MapPin,
  MonitorSmartphone,
  PackageOpen,
  Search,
  Send,
} from "lucide-react";
import { useRouter } from "next/navigation";
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
import { Input } from "@/components/ui/input";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { UpsellAddonRow } from "@/components/upsell/upsell-addon-row";
import { UpsellCarePlanSection } from "@/components/upsell/upsell-care-plan";
import {
  customLineSubtotal,
  toCustomLineRequest,
  UpsellCustomLines,
  type UpsellCustomLineDraft,
} from "@/components/upsell/upsell-custom-lines";
import { UpsellScoreboard } from "@/components/upsell/upsell-scoreboard";
import { UpsellSummaryBar } from "@/components/upsell/upsell-summary-bar";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { upsellApi, type UpsellJob, type UpsellQuote } from "@/lib/api/upsell";
import { queryKeys } from "@/lib/query-keys";
import { STATIC } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import { formatPhoneNumber } from "@/lib/utils/phone";

/** Shared content rail: header, list, and the summary bar's inner content. */
const RAIL = "mx-auto w-full max-w-screen-sm px-4";

/** Above this many add-ons, a search field beats scrolling on a phone. */
const FILTER_THRESHOLD = 8;

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
  const router = useRouter();
  const { can } = useCapabilities();

  const [activeJob, setActiveJob] = useState<UpsellJob | null>(null);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [customLines, setCustomLines] = useState<UpsellCustomLineDraft[]>([]);
  const [createdQuote, setCreatedQuote] = useState<UpsellQuote | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sent, setSent] = useState(false);
  // Care Plan state. The fixture count is a pricing input, so it lives here and
  // drives the query key rather than being posted blind with the proposal.
  const [fixtureCount, setFixtureCount] = useState(0);
  const [carePlanKey, setCarePlanKey] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  // Every query below is gated on this: a technician cannot sell, so firing
  // these would earn a row of 403s and error toasts that read as a broken app
  // rather than as a role boundary. The server refuses them regardless.
  const canSell = can("upsell:sell");

  const jobsQuery = useQuery({
    queryKey: queryKeys.upsell.jobs(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return upsellApi.listJobs(workspaceId);
    },
    enabled: !!workspaceId && canSell,
  });

  const customerQuery = useQuery({
    queryKey: queryKeys.upsell.customer(workspaceId ?? "", activeJob?.id ?? ""),
    queryFn: () => {
      if (!workspaceId || !activeJob) throw new Error("No job");
      return upsellApi.getCustomer(workspaceId, activeJob.id);
    },
    enabled: !!workspaceId && !!activeJob && canSell,
  });

  const catalogQuery = useQuery({
    queryKey: queryKeys.upsell.catalog(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return upsellApi.listCatalog(workspaceId);
    },
    enabled: !!workspaceId && !!activeJob && canSell,
    ...STATIC,
  });

  // Only needed on the job-picker step, so it is not fetched while the technician
  // is mid-proposal.
  const statsQuery = useQuery({
    queryKey: queryKeys.upsell.myStats(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return upsellApi.myStats(workspaceId);
    },
    enabled: !!workspaceId && !activeJob && canSell,
  });

  const carePlanQuery = useQuery({
    queryKey: queryKeys.upsell.carePlans(workspaceId ?? "", fixtureCount),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return upsellApi.listCarePlans(workspaceId, fixtureCount);
    },
    enabled: !!workspaceId && !!activeJob && canSell,
    // Keep the previous prices on screen while a new count is priced, so the
    // tier list does not blank out under the lead's thumb mid-count.
    placeholderData: (previous) => previous,
  });

  const createQuote = useMutation({
    mutationFn: () => {
      if (!workspaceId || !activeJob) throw new Error("No job");
      return upsellApi.createQuote(workspaceId, activeJob.id, {
        line_items: Object.entries(quantities)
          .filter(([, qty]) => qty > 0)
          .map(([catalog_item_id, quantity]) => ({ catalog_item_id, quantity })),
        custom_line_items: customLines.flatMap((line) => {
          const request = toCustomLineRequest(line);
          return request ? [request] : [];
        }),
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

  const presentQuote = useMutation({
    mutationFn: () => {
      if (!workspaceId || !activeJob || !createdQuote) throw new Error("No quote");
      return upsellApi.presentQuote(workspaceId, activeJob.id, createdQuote.id);
    },
    onSuccess: (quote) => {
      if (!quote.public_token) {
        toast.error("We couldn't open that proposal.");
        return;
      }
      setConfirmOpen(false);
      router.push(`/p/quotes/${quote.public_token}`);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "We couldn't open that proposal."));
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
      // The scoreboard's sent-count just changed.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.upsell.myStats(workspaceId ?? ""),
      });
    },
    onError: (error) => {
      // Keep the dialog open and the draft intact: the tech can retry the other
      // rail (or hand the customer the price verbally) without rebuilding.
      toast.error(getApiErrorMessage(error, "We couldn't send that proposal."));
    },
  });

  const jobs = useMemo(() => {
    const items = jobsQuery.data?.items ?? [];
    return [...items].sort(
      (a, b) => Number(b.status === "in_progress") - Number(a.status === "in_progress"),
    );
  }, [jobsQuery.data]);

  const catalogItems = useMemo(() => catalogQuery.data?.items ?? [], [catalogQuery.data]);

  // Filters on name and description so "path" finds "ZDC Modern Color Path
  // Light" and "bistro" finds an item that only says so in its blurb. A selected
  // item stays visible regardless, so filtering can never hide something the
  // technician has already added to the proposal.
  const visibleItems = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return catalogItems;
    return catalogItems.filter(
      (item) =>
        (quantities[item.id] ?? 0) > 0 ||
        item.name.toLowerCase().includes(needle) ||
        (item.description ?? "").toLowerCase().includes(needle),
    );
  }, [catalogItems, filter, quantities]);

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
    const validCustomLines = customLines.filter(
      (line) => toCustomLineRequest(line) !== null,
    );
    return {
      selectedCount: count + validCustomLines.length,
      previewTotal: total + customLineSubtotal(customLines),
    };
  }, [catalogItems, customLines, quantities]);

  const resetToJobs = () => {
    setActiveJob(null);
    setQuantities({});
    setCustomLines([]);
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
  const hasInvalidCustomLine = customLines.some(
    (line) => toCustomLineRequest(line) === null,
  );
  const nothingSelected = selectedCount === 0 && !carePlanKey;

  // What this crew lead may sell on their own. Null for an office tier, or when
  // the workspace configured no limit. The server enforces it either way — this
  // only stops the lead from building a proposal they cannot send, which is the
  // difference between a blocked button and a failure in front of the
  // customer. The care plan is outside the cap, so only hardware counts.
  const proposalLimit = catalogQuery.data?.proposal_limit ?? null;
  const overLimit = proposalLimit !== null && previewTotal > proposalLimit;

  // Selling is a Lead Technician responsibility, so a regular technician who
  // still has the URL bookmarked gets told why rather than a wall of 403s.
  // Placed after the hooks (never before) so the hook order stays stable; the
  // queries are already scoped and the server refuses them regardless.
  if (!can("upsell:sell")) {
    return (
      <PageEmptyState
        title="Only lead techs can sell add-ons"
        description="Spotted an upgrade on this job? Hand it to your lead tech and they can quote it on site."
      />
    );
  }

  // ---------------------------------------------------------------- step 1
  if (!activeJob) {
    return (
      <div className="flex min-h-full flex-col">
        <header className={`${RAIL} pt-6 pb-4`}>
          <h1 className="text-2xl font-semibold tracking-tight">Sell an add-on</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Pick the job you are on.
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
          ) : jobs.length === 0 ? (
            <PageEmptyState
              icon={<CalendarClock className="size-8" />}
              title="No jobs assigned to you"
              description="Add-ons are sold from a job you are on. Ask your dispatcher to assign you one."
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {jobs.map((job) => {
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
                        {job.status === "in_progress" || when ? (
                          <span className="mt-0.5 flex flex-wrap gap-x-1.5 text-sm text-muted-foreground">
                            {job.status === "in_progress" ? (
                              <span className="font-medium text-primary">In progress now</span>
                            ) : null}
                            {job.status === "in_progress" && when ? (
                              <span aria-hidden="true">·</span>
                            ) : null}
                            {when ? <span>{when}</span> : null}
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

          {/* Below the job list: the job is why they opened the app; their
              numbers are what they check on the way past. */}
          {statsQuery.data ? <UpsellScoreboard stats={statsQuery.data} /> : null}
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
          className="-ml-2 mb-2 min-h-11"
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
              Present it to {customer?.full_name ?? "the customer"} here, or send
              them the approval link.
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
        ) : (
          <>
            {catalogItems.length === 0 ? (
              <div className="rounded-lg border bg-card p-4">
                <div className="flex items-start gap-3">
                  <PackageOpen
                    className="mt-0.5 size-5 shrink-0 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <div>
                    <h2 className="font-medium">No price-book add-ons yet</h2>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      Add custom work below, or ask a manager to mark common items as
                      add-ons.
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <>
                <h2 className="sr-only">Add-ons</h2>
                {/* A real lighting price book is ~22 items. Scrolling that one-handed
                    in a yard to find "path light" is the slow path; typing three
                    letters is the fast one. Shown only once the list is long enough
                    to be worth filtering. */}
                {catalogItems.length > FILTER_THRESHOLD ? (
                  <div className="relative mb-2">
                    <Search
                      className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <Input
                      type="search"
                      value={filter}
                      onChange={(event) => setFilter(event.target.value)}
                      placeholder={`Search ${catalogItems.length} add-ons…`}
                      aria-label="Search add-ons"
                      className="h-11 pl-9 text-base"
                    />
                  </div>
                ) : null}
                {visibleItems.length === 0 ? (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    Nothing matches “{filter}”.
                  </p>
                ) : null}
                <ul className="flex flex-col gap-2">
                  {visibleItems.map((item) => {
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
              </>
            )}

            <div className="mt-6">
              <UpsellCustomLines
                lines={customLines}
                onChange={setCustomLines}
                disabled={createQuote.isPending}
              />
            </div>

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
        actionLabel={createdQuote ? "Share proposal" : "Build proposal"}
        pendingLabel="Building…"
        pending={createQuote.isPending}
        disabled={
          createdQuote ? false : nothingSelected || hasInvalidCustomLine || overLimit
        }
        notice={
          !createdQuote && hasInvalidCustomLine
            ? "Finish or remove the incomplete custom line."
            : !createdQuote && overLimit && proposalLimit !== null
              ? `Over your ${formatCurrency(proposalLimit)} limit — ask the office to send it.`
              : null
        }
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
            <DialogTitle>Share this proposal</DialogTitle>
            <DialogDescription>
              Review it with {customer?.full_name ?? "the customer"} on this
              device, or send them a text link
              {customer?.phone_number
                ? ` at ${formatPhoneNumber(customer.phone_number)}`
                : " when a mobile number is available"}
              . The proposal includes
              {createdQuote && createdQuote.total > 0
                ? ` ${formatCurrency(createdQuote.total)} of work`
                : " no one-time work"}
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
              disabled={deliverQuote.isPending || presentQuote.isPending}
              className="min-h-11"
            >
              Not yet
            </Button>
            <Button
              variant="outline"
              onClick={() => presentQuote.mutate()}
              disabled={deliverQuote.isPending || presentQuote.isPending}
              className="min-h-11"
            >
              <MonitorSmartphone className="size-4" aria-hidden="true" />
              {presentQuote.isPending ? "Opening…" : "Present in person"}
            </Button>
            <Button
              onClick={() => deliverQuote.mutate("sms")}
              disabled={
                deliverQuote.isPending ||
                presentQuote.isPending ||
                !customer?.phone_number
              }
              className="min-h-11"
            >
              <Send className="size-4" aria-hidden="true" />
              {deliverQuote.isPending
                ? "Sending…"
                : customer?.phone_number
                  ? "Send text"
                  : "No mobile number"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
