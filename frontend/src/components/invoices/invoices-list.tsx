"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, MoreHorizontal, Plus, Receipt, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
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
import { usePagination } from "@/hooks/usePagination";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { invoicesApi, type InvoicesListParams } from "@/lib/api/invoices";
import { describeInvoiceDelivery } from "@/lib/invoice-delivery";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { formatDate, formatDateTime } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Invoice, InvoiceStatus } from "@/types";

import { InvoiceCreateDialog } from "./invoice-create-dialog";
import { InvoiceEditDialog } from "./invoice-edit-dialog";
import { InvoiceRecordPaymentDialog } from "./invoice-record-payment-dialog";

const STATUS_VARIANT: Record<InvoiceStatus, "default" | "secondary" | "destructive" | "outline"> = {
  draft: "outline",
  sent: "secondary",
  partial: "secondary",
  paid: "default",
  overdue: "destructive",
  void: "outline",
};

const RECEIPT_STATUS = {
  pending: { label: "Pending", variant: "secondary" },
  sent: { label: "Sent", variant: "default" },
  needs_attention: { label: "Needs attention", variant: "destructive" },
  skipped: { label: "Skipped", variant: "outline" },
} as const;

function ReceiptDeliveryCell({ invoice }: { invoice: Invoice }) {
  const delivery = invoice.receipt_delivery ?? { status: "skipped" as const };
  const config = RECEIPT_STATUS[delivery.status];
  return (
    <div className="max-w-56 space-y-1">
      <Badge variant={config.variant}>{config.label}</Badge>
      {delivery.recipient && (
        <p className="truncate text-xs text-muted-foreground" title={delivery.recipient}>
          {delivery.recipient}
        </p>
      )}
      {invoice.payment_method && invoice.status === "paid" && (
        <p className="text-xs font-medium capitalize">Paid by {invoice.payment_method}</p>
      )}
      {delivery.timestamp && (
        <p className="text-xs text-muted-foreground">{formatDateTime(delivery.timestamp)}</p>
      )}
      {delivery.reason && (
        <p className="text-xs text-destructive" title={delivery.reason}>
          {delivery.reason}
        </p>
      )}
    </div>
  );
}

export function InvoicesList() {
  const workspaceId = useWorkspaceId();
  return <WorkspaceInvoicesList key={workspaceId} workspaceId={workspaceId} />;
}

function WorkspaceInvoicesList({ workspaceId }: { workspaceId: string | null }) {
  const queryClient = useQueryClient();
  const { page, pageSize, setPage, reset } = usePagination({ initialPageSize: 100 });
  const [statusFilter, setStatusFilter] = useState("all");
  const [contactId, setContactId] = useState("");
  const hasFilters = statusFilter !== "all" || contactId !== "";
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Invoice | null>(null);
  const [recordingPayment, setRecordingPayment] = useState<Invoice | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Invoice | null>(null);

  const params = {
    page,
    page_size: pageSize,
    status: statusFilter === "all" ? undefined : statusFilter,
    contact_id: contactId ? Number(contactId) : undefined,
  } satisfies InvoicesListParams;
  const query = useQuery({
    queryKey: queryKeys.invoices.list(workspaceId ?? "", params),
    queryFn: () => invoicesApi.list(workspaceId ?? "", params),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });
  const totalPages = Math.max(1, query.data?.pages ?? 1);
  // A deletion or status change can remove the last page; don't reset otherwise.
  if (query.isSuccess && page > totalPages) setPage(totalPages);

  const invalidate = () => {
    if (workspaceId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.invoices.all(workspaceId),
      });
    }
  };

  const sendMutation = useMutation({
    mutationFn: (id: string) => invoicesApi.send(workspaceId ?? "", id),
    onSuccess: (inv) => {
      // Report what actually reached the customer, not just the transition.
      const notice = describeInvoiceDelivery(inv);
      if (notice.tone === "success") {
        toast.success(notice.message);
      } else {
        toast.warning(notice.message, { description: notice.description });
      }
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to send invoice")),
  });

  const retryReceiptMutation = useMutation({
    mutationFn: (invoice: Invoice) => invoicesApi.retryReceipt(workspaceId ?? "", invoice.id),
    onSuccess: (updated) => {
      toast.success(
        updated.receipt_delivery.status === "sent"
          ? `Receipt for ${updated.number} was already sent`
          : `Receipt for ${updated.number} queued`,
      );
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Could not retry the receipt")),
  });

  const voidMutation = useMutation({
    mutationFn: (id: string) => invoicesApi.void(workspaceId ?? "", id),
    onSuccess: (inv) => {
      toast.success(`Invoice ${inv.number} voided`);
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to void invoice")),
  });

  const textMutation = useMutation({
    mutationFn: (invoice: Invoice) =>
      invoicesApi.deliver(workspaceId ?? "", invoice.id, { channel: "sms" }),
    onSuccess: (result) => {
      toast.success(`Invoice texted to ${result.to}`);
      invalidate();
    },
    // The API refuses with an actionable reason (no phone on file, opted out,
    // no SMS number in the workspace) — show it rather than a generic failure.
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to text invoice")),
  });

  const deleteMutation = useMutation({
    mutationFn: (invoice: Invoice) => invoicesApi.delete(workspaceId ?? "", invoice.id),
    onSuccess: (_result, invoice) => {
      toast.success(`Invoice ${invoice.number} deleted`);
      setPendingDelete(null);
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to delete invoice")),
  });

  const newInvoiceButton = (
    <Button onClick={() => setCreateOpen(true)} size="sm">
      <Plus className="mr-1.5 h-4 w-4" />
      New invoice
    </Button>
  );

  let body: React.ReactNode;
  if (!workspaceId || query.isLoading) {
    body = <PageLoadingState message="Loading invoices..." />;
  } else if (query.isError) {
    body = (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Failed to load invoices")}
        onRetry={() => void query.refetch()}
      />
    );
  } else {
    const invoices = query.data?.items ?? [];
    if (invoices.length === 0) {
      body = (
        <PageEmptyState
          icon={<Receipt className="size-8" />}
          title={hasFilters ? "No matching invoices" : "No invoices yet"}
          description={hasFilters
            ? "Try another customer or status, or clear the filters."
            : "Create your first invoice to bill a customer."}
          action={hasFilters ? undefined : newInvoiceButton}
        />
      );
    } else {
      body = (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead>Customer</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Paid</TableHead>
              <TableHead>Receipt</TableHead>
              <TableHead>Due</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {invoices.map((invoice: Invoice) => (
              <TableRow key={invoice.id}>
                <TableCell className="font-medium">{invoice.number}</TableCell>
                <TableCell>
                  {invoice.contact_name ?? (
                    <span className="text-muted-foreground">No customer</span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[invoice.status]}>{invoice.status}</Badge>
                </TableCell>
                <TableCell className="text-right">
                  {formatCurrency(invoice.total, invoice.currency)}
                </TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {formatCurrency(invoice.amount_paid, invoice.currency)}
                </TableCell>
                <TableCell>
                  <ReceiptDeliveryCell invoice={invoice} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {invoice.due_date ? formatDate(invoice.due_date) : "—"}
                </TableCell>
                <TableCell>
                  <RowActions
                    invoice={invoice}
                    onEdit={() => setEditing(invoice)}
                    onSend={() => sendMutation.mutate(invoice.id)}
                    onText={() => textMutation.mutate(invoice)}
                    onRecordPayment={() => setRecordingPayment(invoice)}
                    onRetryReceipt={() => retryReceiptMutation.mutate(invoice)}
                    onVoid={() => voidMutation.mutate(invoice.id)}
                    onDelete={() => setPendingDelete(invoice)}
                    busy={
                      sendMutation.isPending ||
                      retryReceiptMutation.isPending ||
                      voidMutation.isPending ||
                      textMutation.isPending
                    }
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
      <div className="flex items-center justify-end">{newInvoiceButton}</div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full space-y-2 sm:w-72">
          <Label htmlFor="invoice-customer-filter">Customer</Label>
          <ContactPicker
            id="invoice-customer-filter"
            workspaceId={workspaceId}
            value={contactId}
            onChange={(value) => { setContactId(value); reset(); }}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="invoice-status-filter">Status</Label>
          <Select value={statusFilter} onValueChange={(value) => { setStatusFilter(value); reset(); }}>
            <SelectTrigger id="invoice-status-filter" className="w-44">
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
      <p className="text-sm text-muted-foreground">Newest first. Filters apply across all invoices.</p>
      {body}
      {query.isSuccess && (
        <ResourceListPagination
          filteredCount={query.data.items.length}
          totalCount={query.data.total}
          resourceName="invoices"
          page={page}
          totalPages={totalPages}
          onPageChange={query.isFetching ? undefined : setPage}
        />
      )}
      <InvoiceCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
      <InvoiceEditDialog
        invoice={editing}
        open={editing !== null}
        onOpenChange={(next) => {
          if (!next) setEditing(null);
        }}
      />
      <InvoiceRecordPaymentDialog
        key={recordingPayment?.id ?? "closed"}
        invoice={recordingPayment}
        open={recordingPayment !== null}
        onOpenChange={(next) => {
          if (!next) setRecordingPayment(null);
        }}
      />

      {/* Deleting is only offered for drafts, but it still destroys a record —
          confirm with the number so the operator sees which one. */}
      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(next) => {
          if (!next && !deleteMutation.isPending) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete invoice {pendingDelete?.number}?</AlertDialogTitle>
            <AlertDialogDescription>
              This draft has never been sent, so deleting it removes it for good. This can&rsquo;t
              be undone.
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
              {deleteMutation.isPending ? "Deleting\u2026" : "Delete invoice"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

interface RowActionsProps {
  invoice: Invoice;
  onEdit: () => void;
  onSend: () => void;
  onText: () => void;
  onRecordPayment: () => void;
  onRetryReceipt: () => void;
  onVoid: () => void;
  onDelete: () => void;
  busy: boolean;
}

/** Row actions mirror backend invoice lifecycle and receipt retry rules. */
function RowActions({
  invoice,
  onEdit,
  onSend,
  onText,
  onRecordPayment,
  onRetryReceipt,
  onVoid,
  onDelete,
  busy,
}: RowActionsProps) {
  const isVoid = invoice.status === "void";
  const isDraft = invoice.status === "draft";
  const canEdit = !isVoid;
  const canSend = !isVoid && invoice.status !== "paid";
  const canText = canSend && invoice.contact_id != null;
  const canRecordPayment =
    !isVoid && invoice.status !== "paid" && invoice.total > invoice.amount_paid;
  const canRetryReceipt = invoice.receipt_delivery?.status === "needs_attention";
  const canVoid = !isVoid && invoice.status !== "paid";
  const canDelete = isDraft;
  if (!canEdit && !canSend && !canRecordPayment && !canRetryReceipt && !canVoid && !canDelete)
    return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" disabled={busy} aria-label="Actions">
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {canEdit && (
          <DropdownMenuItem onClick={onEdit}>
            {invoice.status === "paid" ? "Edit notes" : "Edit invoice"}
          </DropdownMenuItem>
        )}
        {canSend && (
          <DropdownMenuItem onClick={onSend}>
            {isDraft ? "Send invoice" : "Resend invoice"}
          </DropdownMenuItem>
        )}
        {canText && <DropdownMenuItem onClick={onText}>Text invoice</DropdownMenuItem>}
        {canRecordPayment && (
          <DropdownMenuItem onClick={onRecordPayment}>
            <Banknote className="mr-2 size-4" />
            Record payment
          </DropdownMenuItem>
        )}
        {canRetryReceipt && (
          <DropdownMenuItem onClick={onRetryReceipt}>
            <RotateCcw className="mr-2 size-4" />
            Retry receipt
          </DropdownMenuItem>
        )}
        {canVoid && (
          <DropdownMenuItem variant="destructive" onClick={onVoid}>
            Void invoice
          </DropdownMenuItem>
        )}
        {canDelete && (
          <DropdownMenuItem variant="destructive" onClick={onDelete}>
            Delete draft
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
