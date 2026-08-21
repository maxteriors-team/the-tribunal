"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Banknote,
  Check,
  Copy,
  Eye,
  ExternalLink,
  FileText,
  Mail,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Trash2,
  UserRound,
  Wrench,
  X,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FinancingEstimate } from "@/components/proposal/financing-estimate";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TeamMemberPicker } from "@/components/workspaces/team-member-picker";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { quotesApi } from "@/lib/api/quotes";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { formatDate, formatRelative } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Quote, QuoteDeliverChannel, QuoteStatus } from "@/types";

import { ConvertQuoteDialog } from "./convert-quote-dialog";
import { QuoteEditDialog } from "./quote-edit-dialog";
import { QuoteServicesDialog } from "./quote-services-dialog";
import { depositPaymentMethodLabel, RecordDepositDialog } from "./record-deposit-dialog";

const STATUS_VARIANT: Record<QuoteStatus, "default" | "secondary" | "destructive" | "outline"> = {
  draft: "outline",
  sent: "secondary",
  approved: "default",
  declined: "destructive",
  expired: "outline",
};

export function QuotesList() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [convertQuote, setConvertQuote] = useState<Quote | null>(null);
  const [recordDepositQuote, setRecordDepositQuote] = useState<Quote | null>(null);
  const [editing, setEditing] = useState<Quote | null>(null);
  const [servicesQuote, setServicesQuote] = useState<Quote | null>(null);
  const [assignmentQuote, setAssignmentQuote] = useState<Quote | null>(null);
  const [assignmentUserId, setAssignmentUserId] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Quote | null>(null);

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
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to send quote")),
  });

  // Deliberately separate from `sendMutation`: that one marks the quote sent and
  // emails best-effort, so it reports success even when nobody was emailed. This
  // one names the channel, confirms the destination, and shows the server's own
  // reason on failure — "add a mobile number", "this number opted out" — which
  // is a thing the rep can act on while still standing in the driveway.
  const deliverMutation = useMutation({
    mutationFn: ({ id, channel }: { id: string; channel: QuoteDeliverChannel }) =>
      quotesApi.deliver(workspaceId ?? "", id, channel),
    onSuccess: (result) => {
      toast.success(
        result.channel === "sms"
          ? `Proposal texted to ${result.to}`
          : `Proposal emailed to ${result.to}`,
      );
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Couldn't send the proposal")),
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => quotesApi.approve(workspaceId ?? "", id),
    onSuccess: (q) => {
      toast.success(`Quote ${q.number} approved`);
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to approve quote")),
  });

  const declineMutation = useMutation({
    mutationFn: (id: string) => quotesApi.decline(workspaceId ?? "", id),
    onSuccess: (q) => {
      toast.success(`Quote ${q.number} declined`);
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to decline quote")),
  });

  const deleteMutation = useMutation({
    mutationFn: (quote: Quote) => quotesApi.delete(workspaceId ?? "", quote.id),
    onSuccess: (_result, quote) => {
      toast.success(`Quote ${quote.number} deleted`);
      setPendingDelete(null);
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to delete quote")),
  });

  const assignmentMutation = useMutation({
    mutationFn: ({ quoteId, userId }: { quoteId: string; userId: number | null }) =>
      quotesApi.assign(workspaceId ?? "", quoteId, userId),
    onSuccess: (quote) => {
      toast.success(
        quote.assignee
          ? `Quote ${quote.number} assigned to ${quote.assignee.full_name || quote.assignee.email}`
          : `Quote ${quote.number} is unassigned`,
      );
      setAssignmentQuote(null);
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to update quote owner")),
  });

  const openAssignment = (quote: Quote) => {
    setAssignmentQuote(quote);
    setAssignmentUserId(quote.assigned_user_id ?? null);
  };

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
          description="Quotes created from Light Designer and saved lighting projects appear here."
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
              <TableHead>Owner</TableHead>
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
                    <Badge variant={STATUS_VARIANT[quote.status]}>{quote.status}</Badge>
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
                <TableCell className="max-w-[14rem]">
                  {quote.assignee ? (
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {quote.assignee.full_name || quote.assignee.email}
                      </div>
                      {quote.assignee.full_name ? (
                        <div className="truncate text-xs text-muted-foreground">
                          {quote.assignee.email}
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <span className="text-sm text-muted-foreground">Unassigned</span>
                  )}
                </TableCell>
                <TableCell className="min-w-[18rem] text-right">
                  <div>{formatCurrency(quote.total, quote.currency)}</div>
                  {quote.deposit_paid ? (
                    <div className="mt-1 text-xs font-medium text-emerald-600">
                      Deposit paid
                      {depositPaymentMethodLabel(quote.deposit_payment_method)
                        ? ` · ${depositPaymentMethodLabel(quote.deposit_payment_method)}`
                        : ""}
                    </div>
                  ) : quote.deposit_required && quote.deposit_amount ? (
                    <div className="mt-1 text-xs font-medium text-amber-600">
                      Deposit due · {formatCurrency(quote.deposit_amount, quote.currency)}
                    </div>
                  ) : null}
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
                    onAssign={() => openAssignment(quote)}
                    onEdit={() => setEditing(quote)}
                    onSend={() => sendMutation.mutate(quote.id)}
                    onDeliver={(channel) => deliverMutation.mutate({ id: quote.id, channel })}
                    onApprove={() => approveMutation.mutate(quote.id)}
                    onDecline={() => declineMutation.mutate(quote.id)}
                    onRecordDeposit={() => setRecordDepositQuote(quote)}
                    onConvert={() => setConvertQuote(quote)}
                    onAddServices={() => setServicesQuote(quote)}
                    onCopyLink={() => copyClientLink(quote)}
                    onPreview={() => openClientProposal(quote)}
                    onDelete={() => setPendingDelete(quote)}
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
      {body}
      <ConvertQuoteDialog
        workspaceId={workspaceId ?? ""}
        quote={convertQuote}
        open={convertQuote !== null}
        onOpenChange={(open) => {
          if (!open) setConvertQuote(null);
        }}
      />
      {recordDepositQuote ? (
        <RecordDepositDialog
          workspaceId={workspaceId ?? ""}
          quote={recordDepositQuote}
          open
          onOpenChange={(open) => {
            if (!open) setRecordDepositQuote(null);
          }}
        />
      ) : null}
      <QuoteServicesDialog
        workspaceId={workspaceId ?? ""}
        quote={servicesQuote}
        open={servicesQuote !== null}
        onOpenChange={(open) => {
          if (!open) setServicesQuote(null);
        }}
      />

      <QuoteEditDialog
        quote={editing}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
      />

      <Dialog
        open={assignmentQuote !== null}
        onOpenChange={(open) => {
          if (!open && !assignmentMutation.isPending) setAssignmentQuote(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Assign quote owner</DialogTitle>
            <DialogDescription>
              Choose who owns the sales follow-up for quote {assignmentQuote?.number}. Job crews are
              assigned separately when the quote converts.
            </DialogDescription>
          </DialogHeader>
          {assignmentQuote?.assignee ? (
            <p className="text-sm text-muted-foreground">
              Current owner: {assignmentQuote.assignee.full_name || assignmentQuote.assignee.email}
            </p>
          ) : null}
          <TeamMemberPicker
            workspaceId={workspaceId ?? ""}
            value={assignmentUserId}
            onValueChange={setAssignmentUserId}
            label="Sales owner"
            triggerId="quote-owner"
            disabled={assignmentMutation.isPending}
          />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setAssignmentQuote(null)}
              disabled={assignmentMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!assignmentQuote || assignmentMutation.isPending}
              onClick={() => {
                if (assignmentQuote) {
                  assignmentMutation.mutate({
                    quoteId: assignmentQuote.id,
                    userId: assignmentUserId,
                  });
                }
              }}
            >
              {assignmentMutation.isPending ? "Saving…" : "Save owner"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* A quote can be deleted right up until it is decided, including after
          it went out — so the confirmation has to say which one, and warn when
          a customer is holding a link that is about to stop resolving. */}
      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(next) => {
          if (!next && !deleteMutation.isPending) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete quote {pendingDelete?.number}?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete?.public_token
                ? "This quote has already been sent. Deleting it breaks the proposal link the customer has — if they open it again they'll get a dead page. This can't be undone."
                : "This quote has never been sent, so deleting it removes it for good. This can't be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                // Keep the dialog mounted while the request is in flight.
                event.preventDefault();
                if (pendingDelete) deleteMutation.mutate(pendingDelete);
              }}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "Deleting\u2026" : "Delete quote"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

interface RowActionsProps {
  quote: Quote;
  busy: boolean;
  onAssign: () => void;
  onEdit: () => void;
  onSend: () => void;
  onDeliver: (channel: QuoteDeliverChannel) => void;
  onApprove: () => void;
  onDecline: () => void;
  onRecordDeposit: () => void;
  onConvert: () => void;
  onAddServices: () => void;
  onCopyLink: () => void;
  onPreview: () => void;
  onDelete: () => void;
}

/**
 * Row menu. Each item mirrors a backend rule rather than guessing: the service
 * blocks edits and deletes only once a quote is decided (`approved`,
 * `declined`) or lapsed (`expired`) — a *sent* quote is still live work, so it
 * stays editable and deletable here too.
 */
function RowActions({
  quote,
  busy,
  onAssign,
  onEdit,
  onSend,
  onDeliver,
  onApprove,
  onDecline,
  onRecordDeposit,
  onConvert,
  onAddServices,
  onCopyLink,
  onPreview,
  onDelete,
}: RowActionsProps) {
  const isOpen = quote.status === "draft" || quote.status === "sent";
  const canChangeTerms = Boolean(
    isOpen &&
    !quote.deposit_paid &&
    (!quote.is_wizard_quote || quote.wizard_edit_mode === "update"),
  );
  const isApproved = quote.status === "approved";
  const alreadyConverted = Boolean(quote.converted_job_id && quote.converted_invoice_id);
  const canConvert = isApproved && !alreadyConverted;
  const canRecordDeposit = Boolean(
    quote.deposit_required && quote.status !== "declined" && quote.status !== "expired",
  );
  // The client proposal link only exists once a quote has been sent.
  const hasClientLink = Boolean(quote.public_token);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" disabled={busy} aria-label="Actions">
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={onAssign}>
          <UserRound className="mr-2 h-4 w-4" />
          Assign owner
        </DropdownMenuItem>
        {canRecordDeposit && (
          <DropdownMenuItem onClick={onRecordDeposit}>
            <Banknote className="mr-2 h-4 w-4" />
            Record deposit
          </DropdownMenuItem>
        )}
        {(isOpen || canConvert || hasClientLink || canRecordDeposit) && <DropdownMenuSeparator />}
        {isOpen && (
          <>
            {canChangeTerms && (
              <>
                {/* Basic details remain editable while customer and payment terms are mutable. */}
                <DropdownMenuItem onClick={onEdit}>
                  <Pencil className="mr-2 h-4 w-4" />
                  Edit basic details
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onAddServices}>
                  <Wrench className="mr-2 h-4 w-4" />
                  Add services
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            )}
            {/* Emailing and texting come next: they are what "send it to them"
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
            <DropdownMenuItem onClick={onConvert}>Convert to job &amp; invoice</DropdownMenuItem>
          </>
        )}
        {canChangeTerms && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={onDelete}>
              <Trash2 className="mr-2 h-4 w-4" />
              Delete quote
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
