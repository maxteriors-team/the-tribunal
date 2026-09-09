"use client";

/**
 * Renew last season's homes, one house at a time.
 *
 * The pre-booking campaign texts the whole warm list at once. This is the other
 * half of the same job: the operator picks a house they lit last year and gets a
 * draft quote already carrying last season's line items, tagged as seasonal
 * work. Nothing here re-measures — the roof has not changed.
 *
 * All pricing and line copying happens server-side; this page only picks a
 * customer and navigates to the draft it gets back.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, History, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { useDebouncedSearch } from "@/hooks/useDebouncedSearch";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { christmasRenewalsApi, type RenewalCandidate } from "@/lib/api/christmas-renewals";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

function seasonLabel(signedUpAt: string): string {
  const date = new Date(signedUpAt);
  return Number.isNaN(date.getTime())
    ? "Previous season"
    : date.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

export default function RenewLastSeasonPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();
  const search = useDebouncedSearch({ delay: 300 });
  // Which row is mid-flight, so only its button shows a pending state.
  const [renewingContactId, setRenewingContactId] = useState<number | null>(null);

  const params = search.debouncedValue ? { search: search.debouncedValue } : {};
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.christmasRenewals.list(workspaceId ?? "", params),
    queryFn: () => christmasRenewalsApi.list(workspaceId!, params),
    enabled: !!workspaceId,
  });

  const renew = useMutation({
    mutationFn: (contactId: number) => christmasRenewalsApi.createQuote(workspaceId!, contactId),
    onMutate: (contactId) => setRenewingContactId(contactId),
    onSuccess: (quote) => {
      // The renewal wrote a quote, so the quote list is what went stale.
      void queryClient.invalidateQueries({ queryKey: queryKeys.quotes.all(workspaceId ?? "") });
      toast.success(`Draft ${quote.number} created from last season's quote`);
      router.push(`/quotes/${quote.id}`);
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't create the renewal quote")),
    onSettled: () => setRenewingContactId(null),
  });

  const items = data?.items ?? [];

  return (
    <AppSidebar>
      <div className="app-scrollbar h-full overflow-y-auto">
        <div className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-6 sm:py-8">
          <Button variant="ghost" size="sm" asChild className="-ml-2 mb-4">
            <Link href="/christmas-lights">
              <ArrowLeft className="size-4" />
              Christmas Light Estimator
            </Link>
          </Button>

          <header className="flex items-start gap-4">
            <span
              className="flex size-12 shrink-0 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              aria-hidden="true"
            >
              <History className="size-6" />
            </span>
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight">
                Renew Last Season&rsquo;s Homes
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Pick a house you lit before and we&rsquo;ll draft{" "}
                {data ? `the ${data.season_year} quote` : "this season's quote"} with last
                season&rsquo;s line items already on it.
              </p>
            </div>
          </header>

          <div className="relative mt-6">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              className="pl-9"
              placeholder="Search by customer or quote number"
              aria-label="Search last season's customers"
              value={search.value}
              onChange={(event) => search.setValue(event.target.value)}
            />
          </div>

          <div className="mt-4">
            {isPending ? (
              <PageLoadingState message="Loading last season's homes…" />
            ) : isError ? (
              <PageErrorState
                title="Couldn't load last season's homes"
                onRetry={() => void refetch()}
              />
            ) : items.length === 0 ? (
              <PageEmptyState
                title={
                  search.debouncedValue
                    ? "No matching customers"
                    : "No previous seasons on record yet"
                }
                description={
                  search.debouncedValue
                    ? "Try a different name or quote number."
                    : "Once a holiday quote is approved, that customer shows up here next season."
                }
              />
            ) : (
              <ul className="flex flex-col gap-2">
                {items.map((candidate: RenewalCandidate) => (
                  <li key={candidate.contact_id}>
                    <Card>
                      <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
                        <div className="min-w-0">
                          <p className="truncate font-medium">{candidate.contact_name}</p>
                          <p className="mt-0.5 text-sm text-muted-foreground">
                            {seasonLabel(candidate.signed_up_at)} &middot; {candidate.quote_number}{" "}
                            &middot; {candidate.line_item_count}{" "}
                            {candidate.line_item_count === 1 ? "line" : "lines"} &middot;{" "}
                            {currency.format(candidate.quote_total)}
                          </p>
                        </div>
                        <Button
                          onClick={() => renew.mutate(candidate.contact_id)}
                          disabled={renew.isPending}
                        >
                          {renewingContactId === candidate.contact_id
                            ? "Creating…"
                            : "Create renewal quote"}
                        </Button>
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </AppSidebar>
  );
}
