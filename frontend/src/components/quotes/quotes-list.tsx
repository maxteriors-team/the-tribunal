"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  Eye,
  ExternalLink,
  FileText,
  Mail,
  MessageSquare,
  MoreHorizontal,
  Plus,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FinancingEstimate } from "@/components/proposal/financing-estimate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
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
import { POLL_60S } from "@/lib/query-options";
import { formatDate, formatRelative } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Quote, QuoteDeliverChannel, QuoteStatus } from "@/types";

import { ConvertQuoteDialog } from "./convert-quote-dialog";

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

export function QuotesList() {
  const workspaceId = useWorkspaceId();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [convertQuote, setConvertQuote] = useState<Quote | null>(null);

  const query = useQuery({
    queryKey: queryKeys.quotes.list(workspaceId ?? ""),
    queryFn: () => quotesApi.list(workspaceId ?? "", { page_size: 100 }),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });

  const invalidate = () => {
    if (workspaceId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.quotes.all(workspaceId),
      });
    }
  };

  const sendMutation = useMutation({
    mutationFn: (id: string) => quotesApi.send(workspaceId ?? "", id),
    onSuccess: (q) => {
      toast.success(`Quote ${q.number} sent`);
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to send quote")),
  });

  // Deliberately separate from `sendMutation`: that one marks the quote sent and
  // emails best-effort, so it reports success even when nobody was emailed. This
  // one names the channel, confirms the destination, and shows the server's own
  // reason on failure — "add a mobile number", "this number opted out" — which
  // is a thing the rep can act on while still standing in the driveway.
  const deliverMutation = useMutation({
    mutationFn: ({
      id,
      channel,
    }: {
      id: string;
      channel: QuoteDeliverChannel;
    }) => quotesApi.deliver(workspaceId ?? "", id, channel),
    onSuccess: (result) => {
      toast.success(
        result.channel === "sms"
          ? `Proposal texted to ${result.to}`
          : `Proposal emailed to ${result.to}`,
      );
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Couldn't send the proposal")),
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => quotesApi.approve(workspaceId ?? "", id),
    onSuccess: (q) => {
      toast.success(`Quote ${q.number} approved`);
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to approve quote")),
  });

  const declineMutation = useMutation({
    mutationFn: (id: string) => quotesApi.decline(workspaceId ?? "", id),
    onSuccess: (q) => {
      toast.success(`Quote ${q.number} declined`);
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to decline quote")),
  });

  const busy =
    sendMutation.isPending ||
    deliverMutation.isPending ||
    approveMutation.isPending ||
    declineMutation.isPending;

  const clientProposalUrl = (quote: Quote): string | null =>
    quote.public_token ? `${window.location.origin}/p/quotes/${quote.public_token}` : null;

  const copyClientLink = (quote: Quote) => {
    const url = clientProposalUrl(quote);
    if (!url) return;
    void navigator.clipboard
      .writeText(url)
      .then(() => toast.success("Client proposal link copied"))
      .catch(() => toast.error("Couldn't copy link"));
  };

  // Staff preview opens the exact customer URL, so it must announce itself:
  // `?preview=1` tells the public page to skip its view beacon. Without it every
  // internal peek would register as a client view and fire a false "your client
  // just opened it" alert. Deliberately not added by `copyClientLink` — the link
  // the customer receives must never carry the flag.
  const openClientProposal = (quote: Quote) => {
    const url = clientProposalUrl(quote);
    if (url) window.open(`${url}?preview=1`, "_blank", "noopener,noreferrer");
  };

  // Consolidated entry point: every new quote is built in the sales wizard (the
  // single quoting system), which prices every line server-side and saves one
  // Quote with its rich proposal snapshot.
  const newQuoteButton = (
    <Button onClick={() => router.push("/sales-wizard")} size="sm">
      <Plus className="mr-1.5 h-4 w-4" />
      New quote
    </Button>
  );

  let body: React.ReactNode;
  if (!workspaceId || query.isLoading) {
    body = <PageLoadingState message="Loading quotes..." />;
  } else if (query.isError) {
    body = (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Failed to load quotes")}
        onRetry={() => void query.refetch()}
      />
    );
  } else {
    const quotes = query.data?.items ?? [];
    if (quotes.length === 0) {
      body = (
        <PageEmptyState
          icon={<FileText className="size-8" />}
          title="No quotes yet"
          description="Create your first quote to send a customer an estimate."
          action={newQuoteButton}
        />
      );
    } else {
      body = (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead>For</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead>Valid until</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {quotes.map((quote: Quote) => (
              <TableRow key={quote.id}>
                <TableCell className="font-medium">{quote.number}</TableCell>
                <TableCell className="max-w-[16rem] truncate text-muted-foreground">
                  {quote.title || "—"}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <Badge variant={STATUS_VARIANT[quote.status]}>
                      {quote.status}
                    </Badge>
                    {(quote.converted_job_id || quote.converted_invoice_id) && (
                      <Badge variant="outline" className="text-emerald-600">
                        converted
                      </Badge>
                    )}
                  </div>
                  {/* The buying signal: they have it open, call them. Muted so
                      it reads as context under the status, not a second badge. */}
                  {quote.last_viewed_at && (
                    <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                      <Eye className="h-3 w-3" aria-hidden="true" />
                      <span>Viewed {formatRelative(quote.last_viewed_at)}</span>
                    </div>
                  )}
                </TableCell>
                <TableCell className="min-w-[18rem] text-right">
                  <div>{formatCurrency(quote.total, quote.currency)}</div>
                  <FinancingEstimate
                    financing={quote.financing}
                    variant="compact"
                    className="quote-financing-estimate"
                  />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {quote.expiry_date ? formatDate(quote.expiry_date) : "—"}
                </TableCell>
                <TableCell>
                  <RowActions
                    quote={quote}
                    busy={busy}
                    onSend={() => sendMutation.mutate(quote.id)}
                    onDeliver={(channel) =>
                      deliverMutation.mutate({ id: quote.id, channel })
                    }
                    onApprove={() => approveMutation.mutate(quote.id)}
                    onDecline={() => declineMutation.mutate(quote.id)}
                    onConvert={() => setConvertQuote(quote)}
                    onCopyLink={() => copyClientLink(quote)}
                    onPreview={() => openClientProposal(quote)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      );
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">{newQuoteButton}</div>
      {body}
      <ConvertQuoteDialog
        workspaceId={workspaceId ?? ""}
        quote={convertQuote}
        open={convertQuote !== null}
        onOpenChange={(open) => {
          if (!open) setConvertQuote(null);
        }}
      />
    </div>
  );
}

interface RowActionsProps {
  quote: Quote;
  busy: boolean;
  onSend: () => void;
  onDeliver: (channel: QuoteDeliverChannel) => void;
  onApprove: () => void;
  onDecline: () => void;
  onConvert: () => void;
  onCopyLink: () => void;
  onPreview: () => void;
}

function RowActions({
  quote,
  busy,
  onSend,
  onDeliver,
  onApprove,
  onDecline,
  onConvert,
  onCopyLink,
  onPreview,
}: RowActionsProps) {
  const isOpen = quote.status === "draft" || quote.status === "sent";
  const isApproved = quote.status === "approved";
  const alreadyConverted = Boolean(
    quote.converted_job_id && quote.converted_invoice_id
  );
  const canConvert = isApproved && !alreadyConverted;
  // The client proposal link only exists once a quote has been sent.
  const hasClientLink = Boolean(quote.public_token);

  if (!isOpen && !canConvert && !hasClientLink) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" disabled={busy} aria-label="Actions">
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {isOpen && (
          <>
            {/* Emailing and texting come first: they are what "send it to them"
                actually means to a rep. Both work straight from a draft — the
                server marks the quote sent and mints its client link on the way
                out, so there is no "send first, then deliver" two-step. */}
            <DropdownMenuItem onClick={() => onDeliver("email")}>
              <Mail className="mr-2 h-4 w-4" />
              Email proposal to client
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onDeliver("sms")}>
              <MessageSquare className="mr-2 h-4 w-4" />
              Text proposal to client
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={onSend}>
              {quote.status === "draft" ? "Mark as sent" : "Re-send email"}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onApprove}>
              <Check className="mr-2 h-4 w-4" />
              Approve
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={onDecline}>
              <X className="mr-2 h-4 w-4" />
              Decline
            </DropdownMenuItem>
          </>
        )}
        {hasClientLink && (
          <>
            {isOpen && <DropdownMenuSeparator />}
            <DropdownMenuItem onClick={onPreview}>
              <ExternalLink className="mr-2 h-4 w-4" />
              Preview client proposal
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onCopyLink}>
              <Copy className="mr-2 h-4 w-4" />
              Copy client link
            </DropdownMenuItem>
          </>
        )}
        {canConvert && (
          <>
            {(isOpen || hasClientLink) && <DropdownMenuSeparator />}
            <DropdownMenuItem onClick={onConvert}>
              Convert to job &amp; invoice
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
