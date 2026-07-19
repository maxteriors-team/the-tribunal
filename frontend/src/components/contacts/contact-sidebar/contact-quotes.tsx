"use client";

import { ExternalLink, FileText, Loader2 } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatCurrency } from "@/lib/utils/number";
import type { Quote, QuoteStatus } from "@/types";

/** Badge tone per quote status — mirrors the Quotes list for one visual language. */
const STATUS_VARIANT: Record<
  QuoteStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  draft: "outline",
  sent: "secondary",
  approved: "default",
  declined: "destructive",
  expired: "outline",
};

interface ContactQuotesProps {
  quotes: Quote[];
  isLoading: boolean;
}

/**
 * Quotes filed on this customer record, surfaced on the contact profile so the
 * link a saved quote already carries (via ``contact_id``) is actually visible.
 * Each row shows status + total (and deposit when one is owed) and links to the
 * client-facing proposal page when the quote has been shared.
 */
export function ContactQuotes({ quotes, isLoading }: ContactQuotesProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground px-2">Quotes</h3>
      {isLoading ? (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      ) : quotes.length === 0 ? (
        <p className="text-xs text-muted-foreground px-2 py-2">No quotes yet</p>
      ) : (
        <div className="space-y-2 px-2">
          {quotes.slice(0, 3).map((quote) => {
            const clientLink = quote.public_token
              ? `/p/quotes/${quote.public_token}`
              : null;
            const deposit =
              quote.deposit_required && quote.deposit_amount
                ? quote.deposit_amount
                : null;
            return (
              <div
                key={quote.id}
                className="flex items-center gap-2 p-2 rounded-lg bg-muted/30 text-xs"
              >
                <FileText className="h-3 w-3 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">
                    {quote.title || `Quote ${quote.number}`}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {formatCurrency(quote.total)}
                    {deposit
                      ? ` · ${formatCurrency(deposit)} deposit due`
                      : ""}
                  </p>
                </div>
                <Badge
                  variant={STATUS_VARIANT[quote.status]}
                  className="text-xs py-0 capitalize"
                >
                  {quote.status}
                </Badge>
                {clientLink ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0"
                    title="Open client proposal"
                    aria-label="Open client proposal"
                    asChild
                  >
                    <Link href={clientLink} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  </Button>
                ) : null}
              </div>
            );
          })}
          {quotes.length > 3 && (
            <Button variant="outline" size="sm" className="w-full text-xs" asChild>
              <Link href="/quotes">View all ({quotes.length})</Link>
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
