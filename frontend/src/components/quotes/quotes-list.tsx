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
  RotateCcw,
  Trash2,
  UserRound,
  Wrench,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FinancingEstimate } from "@/components/proposal/financing-estimate";
import { ResourceListPagination } from "@/components/resource-list/resource-list-pagination";
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
import { ContactPicker } from "@/components/ui/contact-combobox";
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
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TeamMemberPicker } from "@/components/workspaces/team-member-picker";
import { usePagination } from "@/hooks/usePagination";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { lightingProjectsApi } from "@/lib/api/lighting-projects";
import { quotesApi, type QuotesListParams } from "@/lib/api/quotes";
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

const canEditQuote = (quote: Quote) =>
  (quote.status === "draft" || quote.status === "sent") &&
  !quote.deposit_paid &&
  (!quote.is_wizard_quote || quote.wizard_edit_mode === "update");

const canOpenQuote = (quote: Quote) => Boolean(quote.lighting_project_id) || canEditQuote(quote);

export function QuotesList() {
  const workspaceId = useWorkspaceId();
  return <WorkspaceQuotesList key={workspaceId} workspaceId={workspaceId} />;
}

function WorkspaceQuotesList({ workspaceId }: { workspaceId: string | null }) {
  const queryClient = useQueryClient();
  const { page, pageSize, setPage, reset } = usePagination({ initialPageSize: 100 });
  const [statusFilter, setStatusFilter] = useState("all");
  const [contactId, setContactId] = useState("");
  const hasFilters = statusFilter !== "all" || contactId !== "";
  const router = useRouter();
  const [convertQuote, setConvertQuote] = useState<Quote | null>(null);
  const [recordDepositQuote, setRecordDepositQuote] = useState<Quote | null>(null);
  const [editing, setEditing] = useState<Quote | null>(null);
  const [servicesQuote, setServicesQuote] = useState<Quote | null>(null);
  const [assignmentQuote, setAssignmentQuote] = useState<Quote | null>(null);
  const [assignmentUserId, setAssignmentUserId] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Quote | null>(null);

  const params = {
    page,
    page_size: pageSize,
    status: statusFilter === "all" ? undefined : statusFilter,
    contact_id: contactId ? Number(contactId) : undefined,
  } satisfies QuotesListParams;
  const query = useQuery({
    queryKey: queryKeys.quotes.list(workspaceId ?? "", params),
    queryFn: () => quotesApi.list(workspaceId ?? "", params),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });
  const totalPages = Math.max(1, query.data?.pages ?? 1);
  // A deletion or status change can remove the last page; don't reset otherwise.
  if (query.isSuccess && page > totalPages) setPage(totalPages);

  const invalidate = () => {
    if (workspaceId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.quotes.all(workspaceId),
      });
    }
  };

  const markSentMutation = useMutation({
    mutationFn: (id: string) => quotesApi.markSent(workspaceId ?? "", id),
    onSuccess: () => {
      toast.success("Quote marked as sent", { description: "No email or text was sent." });
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to mark quote as sent")),
  });

  // Only checked delivery can claim a send; status changes send nothing.
  const deliverMutation = useMutation({
    mutationFn: ({ id, channel }: { id: string; channel: QuoteDeliverChannel }) =>
      quotesApi.deliver(workspaceId ?? "", id, channel),
    onSuccess: (result) => {
      toast.success(
        result.channel === "sms"
          ? `Proposal texted to ${result.to}`
          : `Quote email to ${result.to} accepted for delivery`,
      );
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Couldn't send the proposal")),
    // A failed delivery can still publish the quote; refresh its status and link.
    onSettled: invalidate,
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

  const reopenMutation = useMutation({
    mutationFn: (id: string) => quotesApi.reopen(workspaceId ?? "", id),
    onSuccess: (q) => {
      toast.success(
        q.expiry_date
          ? `Quote ${q.number} reopened until ${formatDate(q.expiry_date)}`
          : `Quote ${q.number} reopened`,
      );
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to reopen quote")),
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

  const openQuote = async (quote: Quote) => {
    if (!quote.lighting_project_id) {
      setEditing(quote);
      return;
    }
    if (!workspaceId) return;

    try {
      const project = await lightingProjectsApi.get(workspaceId, quote.lighting_project_id);
      queryClient.setQueryData(queryKeys.lightingProjects.detail(workspaceId, project.id), project);
      router.push(
        `/${project.project_type === "permanent" ? "permanent-lighting" : "landscape-lighting"}/${project.id}`,
      );
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "Could not open the linked lighting project"));
    }
  };

  const busy =
    markSentMutation.isPending ||
    deliverMutation.isPending ||
    approveMutation.isPending ||
    declineMutation.isPending ||
    reopenMutation.isPending;

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
          title={hasFilters ? "No matching quotes" : "No quotes yet"}
          description={hasFilters
            ? "Try another customer or status, or clear the filters."
            : "Quotes created from Light Designer and saved lighting projects appear here."}
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
                <TableCell className="font-medium">
                  {canOpenQuote(quote) ? (
                    <button
                      type="button"
                      className="underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      onClick={() => void openQuote(quote)}
                    >
                      {quote.number}
                    </button>
                  ) : (
                    quote.number
                  )}
                </TableCell>
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
                    onMarkSent={() => markSentMutation.mutate(quote.id)}
                    onDeliver={(channel) => deliverMutation.mutate({ id: quote.id, channel })}
                    onApprove={() => approveMutation.mutate(quote.id)}
                    onDecline={() => declineMutation.mutate(quote.id)}
                    onReopen={() => reopenMutation.mutate(quote.id)}
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
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full space-y-2 sm:w-72">
          <Label htmlFor="quote-customer-filter">Customer</Label>
          <ContactPicker
            id="quote-customer-filter"
            workspaceId={workspaceId}
            value={contactId}
            onChange={(value) => { setContactId(value); reset(); }}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="quote-status-filter">Status</Label>
          <Select value={statusFilter} onValueChange={(value) => { setStatusFilter(value); reset(); }}>
            <SelectTrigger id="quote-status-filter" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {Object.keys(STATUS_VARIANT).map((status) => (
                <SelectItem key={status} value={status}>
                  {status.charAt(0).toUpperCase() + status.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {hasFilters && (
          <Button variant="ghost" onClick={() => { setStatusFilter("all"); setContactId(""); reset(); }}>
            Clear filters
          </Button>
        )}
      </div>
      <p className="text-sm text-muted-foreground">Newest first. Filters apply across all quotes.</p>
      {body}
      {query.isSuccess && (
        <ResourceListPagination
          filteredCount={query.data.items.length}
          totalCount={query.data.total}
          resourceName="quotes"
          page={page}
          totalPages={totalPages}
          onPageChange={query.isFetching ? undefined : setPage}
        />
      )}
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
  onMarkSent: () => void;
  onDeliver: (channel: QuoteDeliverChannel) => void;
  onApprove: () => void;
  onDecline: () => void;
  onReopen: () => void;
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
  onMarkSent,
  onDeliver,
  onApprove,
  onDecline,
  onReopen,
  onRecordDeposit,
  onConvert,
  onAddServices,
  onCopyLink,
  onPreview,
  onDelete,
}: RowActionsProps) {
  const isOpen = quote.status === "draft" || quote.status === "sent";
  // Expiry is the one terminal status the customer never chose — the clock ran
  // out — so unlike approved/declined it is offered back as a reversible action.
  const canReopen = quote.status === "expired";
  const canChangeTerms = canEditQuote(quote);
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
                  Manage services
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
            {quote.status === "draft" ? (
              <DropdownMenuItem onClick={onMarkSent}>
                Mark as sent (no email)
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onClick={() => onDeliver("email")}>
                Re-send email
              </DropdownMenuItem>
            )}
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
        {canReopen && (
          <DropdownMenuItem onClick={onReopen}>
            <RotateCcw className="mr-2 h-4 w-4" />
            Reopen quote
          </DropdownMenuItem>
        )}
        {hasClientLink && (
          <>
            {isOpen && <DropdownMenuSeparator />}
            <DropdownMenuItem onClick={onPreview}>
              <ExternalLink className="mr-2 h-4 w-4" />
              {quote.deposit_required && !quote.deposit_paid
                ? "Open customer payment page"
                : "Preview client proposal"}
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
