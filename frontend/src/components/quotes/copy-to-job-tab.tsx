"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Check, ClipboardCopy, Clock3, ImageOff } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { quotesApi } from "@/lib/api/quotes";
import { queryKeys } from "@/lib/query-keys";
import { formatCurrency } from "@/lib/utils/number";
import type { Quote } from "@/types";

import { ConvertQuoteDialog } from "./convert-quote-dialog";

// simplification: one request covers 500 approved records; paginate if a workspace exceeds it.
const APPROVED_QUOTES_PARAMS = { page_size: 500, status: "approved" };

function QuoteJobAction({
  quote,
  onCopy,
  fullWidth = false,
}: {
  quote: Quote;
  onCopy: () => void;
  fullWidth?: boolean;
}) {
  const className = fullWidth ? "w-full" : undefined;
  return quote.converted_job_id ? (
    <Button variant="outline" size="sm" className={className} asChild>
      <Link href={`/calendar?job=${quote.converted_job_id}`}>
        <CalendarDays className="size-4" /> Open job
      </Link>
    </Button>
  ) : (
    <Button size="sm" className={className} onClick={onCopy}>
      <Clock3 className="size-4" /> Copy to job
    </Button>
  );
}

/** Approved estimates ready to become scheduled field-service jobs. */
export function CopyToJobTab() {
  const workspaceId = useWorkspaceId();
  const [selectedQuote, setSelectedQuote] = useState<Quote | null>(null);
  const quotesQuery = useQuery({
    queryKey: queryKeys.quotes.list(workspaceId ?? "", APPROVED_QUOTES_PARAMS),
    queryFn: () => quotesApi.list(workspaceId ?? "", APPROVED_QUOTES_PARAMS),
    enabled: Boolean(workspaceId),
  });

  if (!workspaceId || quotesQuery.isPending) {
    return <PageLoadingState message="Loading approved estimates…" />;
  }

  if (quotesQuery.error) {
    return (
      <PageErrorState
        message="Approved estimates could not be loaded."
        onRetry={() => void quotesQuery.refetch()}
      />
    );
  }

  const quotes = quotesQuery.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-md bg-primary/10 p-2 text-primary">
            <ClipboardCopy className="size-5" />
          </div>
          <div className="space-y-1">
            <h2 className="font-semibold">Turn approved work into an installation job</h2>
            <p className="max-w-3xl text-sm text-muted-foreground">
              The job keeps the estimate title, job description, and linked installation layout.
              Choose the installation team and time window here; assigned members see it on their
              calendar and track time from the job.
            </p>
          </div>
        </div>
      </div>

      {quotes.length === 0 ? (
        <PageEmptyState
          title="No approved estimates or quotes"
          description="Approve an estimate in the Quotes tab before copying it to a job."
          icon={<ClipboardCopy className="size-8" />}
        />
      ) : (
        <>
          <div className="space-y-3 md:hidden">
            {quotes.map((quote) => (
              <article key={quote.id} className="space-y-3 rounded-lg border bg-card p-4">
                <div>
                  <h3 className="font-medium">{quote.title || quote.number}</h3>
                  <p className="text-xs text-muted-foreground">
                    {quote.number} · {formatCurrency(quote.total, quote.currency)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Job description
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {quote.notes?.trim() || "No job description added"}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Installation layout
                  </p>
                  {quote.lighting_project_id ? (
                    <span className="mt-1 inline-flex items-center gap-1.5 text-sm">
                      <Check className="size-4 text-emerald-600" /> Included
                    </span>
                  ) : (
                    <span className="mt-1 inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                      <ImageOff className="size-4" /> None linked
                    </span>
                  )}
                </div>
                <QuoteJobAction quote={quote} onCopy={() => setSelectedQuote(quote)} fullWidth />
              </article>
            ))}
          </div>

          <div className="hidden overflow-x-auto rounded-md border md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Estimate or quote</TableHead>
                  <TableHead>Job description</TableHead>
                  <TableHead>Installation layout</TableHead>
                  <TableHead className="text-right">Job</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {quotes.map((quote) => (
                  <TableRow key={quote.id}>
                    <TableCell>
                      <div className="font-medium">{quote.title || quote.number}</div>
                      <div className="text-xs text-muted-foreground">
                        {quote.number} · {formatCurrency(quote.total, quote.currency)}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-sm">
                      <p className="line-clamp-2 text-sm text-muted-foreground">
                        {quote.notes?.trim() || "No job description added"}
                      </p>
                    </TableCell>
                    <TableCell>
                      {quote.lighting_project_id ? (
                        <span className="inline-flex items-center gap-1.5 text-sm">
                          <Check className="size-4 text-emerald-600" /> Included
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                          <ImageOff className="size-4" /> None linked
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <QuoteJobAction quote={quote} onCopy={() => setSelectedQuote(quote)} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}

      <ConvertQuoteDialog
        workspaceId={workspaceId}
        quote={selectedQuote}
        open={selectedQuote !== null}
        onOpenChange={(open) => !open && setSelectedQuote(null)}
        mode="copy-to-job"
      />
    </div>
  );
}
