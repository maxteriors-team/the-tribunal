"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, FileText, MoreHorizontal, Plus, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Quote, QuoteStatus } from "@/types";

import { QuoteCreateDialog } from "./quote-create-dialog";

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
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

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

  const convertMutation = useMutation({
    mutationFn: (id: string) => quotesApi.convert(workspaceId ?? "", id),
    onSuccess: (result) => {
      const parts: string[] = [];
      if (result.job_id) parts.push("job");
      if (result.invoice_id) parts.push("invoice");
      toast.success(
        parts.length
          ? `Converted to ${parts.join(" + ")}`
          : "Quote converted"
      );
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to convert quote")),
  });

  const busy =
    sendMutation.isPending ||
    approveMutation.isPending ||
    declineMutation.isPending ||
    convertMutation.isPending;

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

  const openClientProposal = (quote: Quote) => {
    const url = clientProposalUrl(quote);
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  };

  const newQuoteButton = (
    <Button onClick={() => setCreateOpen(true)} size="sm">
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
                </TableCell>
                <TableCell className="text-right">
                  {formatCurrency(quote.total, quote.currency)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {quote.expiry_date ? formatDate(quote.expiry_date) : "—"}
                </TableCell>
                <TableCell>
                  <RowActions
                    quote={quote}
                    busy={busy}
                    onSend={() => sendMutation.mutate(quote.id)}
                    onApprove={() => approveMutation.mutate(quote.id)}
                    onDecline={() => declineMutation.mutate(quote.id)}
                    onConvert={() => convertMutation.mutate(quote.id)}
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
      <QuoteCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}

interface RowActionsProps {
  quote: Quote;
  busy: boolean;
  onSend: () => void;
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
            <DropdownMenuItem onClick={onSend}>
              {quote.status === "draft" ? "Send quote" : "Resend quote"}
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
