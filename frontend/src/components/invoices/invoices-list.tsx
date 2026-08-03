"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Plus, Receipt } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
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
import { invoicesApi } from "@/lib/api/invoices";
import { describeInvoiceDelivery } from "@/lib/invoice-delivery";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Invoice, InvoiceStatus } from "@/types";

import { InvoiceCreateDialog } from "./invoice-create-dialog";
import { InvoiceEditDialog } from "./invoice-edit-dialog";

const STATUS_VARIANT: Record<
  InvoiceStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  draft: "outline",
  sent: "secondary",
  partial: "secondary",
  paid: "default",
  overdue: "destructive",
  void: "outline",
};

export function InvoicesList() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Invoice | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Invoice | null>(null);

  const query = useQuery({
    queryKey: queryKeys.invoices.list(workspaceId ?? ""),
    queryFn: () => invoicesApi.list(workspaceId ?? "", { page_size: 100 }),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });

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
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to send invoice")),
  });

  const voidMutation = useMutation({
    mutationFn: (id: string) => invoicesApi.void(workspaceId ?? "", id),
    onSuccess: (inv) => {
      toast.success(`Invoice ${inv.number} voided`);
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to void invoice")),
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
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to text invoice")),
  });

  const deleteMutation = useMutation({
    mutationFn: (invoice: Invoice) =>
      invoicesApi.delete(workspaceId ?? "", invoice.id),
    onSuccess: (_result, invoice) => {
      toast.success(`Invoice ${invoice.number} deleted`);
      setPendingDelete(null);
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to delete invoice")),
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
          title="No invoices yet"
          description="Create your first invoice to bill a customer."
          action={newInvoiceButton}
        />
      );
    } else {
      body = (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Paid</TableHead>
              <TableHead>Due</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {invoices.map((invoice: Invoice) => (
              <TableRow key={invoice.id}>
                <TableCell className="font-medium">{invoice.number}</TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[invoice.status]}>
                    {invoice.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  {formatCurrency(invoice.total, invoice.currency)}
                </TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {formatCurrency(invoice.amount_paid, invoice.currency)}
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
                    onVoid={() => voidMutation.mutate(invoice.id)}
                    onDelete={() => setPendingDelete(invoice)}
                    busy={
                      sendMutation.isPending ||
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
      {body}
      <InvoiceCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
      <InvoiceEditDialog
        invoice={editing}
        open={editing !== null}
        onOpenChange={(next) => {
          if (!next) setEditing(null);
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
            <AlertDialogTitle>
              Delete invoice {pendingDelete?.number}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This draft has never been sent, so deleting it removes it for good.
              This can&rsquo;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>
              Cancel
            </AlertDialogCancel>
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
  onVoid: () => void;
  onDelete: () => void;
  busy: boolean;
}

/**
 * Row menu. Each item mirrors a backend rule rather than guessing:
 * a voided invoice is frozen, a paid one keeps its lines as history (but its
 * notes stay editable), and only an unsent draft can be destroyed — anything
 * the customer has seen gets voided so the record survives.
 */
function RowActions({
  invoice,
  onEdit,
  onSend,
  onText,
  onVoid,
  onDelete,
  busy,
}: RowActionsProps) {
  const isVoid = invoice.status === "void";
  const isDraft = invoice.status === "draft";
  // Void is terminal; everything else stays editable (a paid invoice opens with
  // its line items locked, matching the service's own guard).
  const canEdit = !isVoid;
  const canSend = !isVoid && invoice.status !== "paid";
  // Texting needs someone to text. Whether that contact actually has a phone
  // isn't on the list row, so the API decides and returns a reason we surface.
  const canText = canSend && invoice.contact_id != null;
  const canVoid = !isVoid && invoice.status !== "paid";
  // Issued invoices are accounting records: void, never delete.
  const canDelete = isDraft;
  if (!canEdit && !canSend && !canVoid && !canDelete) return null;

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
        {canText && (
          <DropdownMenuItem onClick={onText}>Text invoice</DropdownMenuItem>
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
