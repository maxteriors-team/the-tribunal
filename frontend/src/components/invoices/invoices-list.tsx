"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Plus, Receipt } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Invoice, InvoiceStatus } from "@/types";

import { InvoiceCreateDialog } from "./invoice-create-dialog";

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
      toast.success(`Invoice ${inv.number} sent`);
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
                    onSend={() => sendMutation.mutate(invoice.id)}
                    onVoid={() => voidMutation.mutate(invoice.id)}
                    busy={sendMutation.isPending || voidMutation.isPending}
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
    </div>
  );
}

interface RowActionsProps {
  invoice: Invoice;
  onSend: () => void;
  onVoid: () => void;
  busy: boolean;
}

function RowActions({ invoice, onSend, onVoid, busy }: RowActionsProps) {
  const canSend = invoice.status !== "void" && invoice.status !== "paid";
  const canVoid = invoice.status !== "void" && invoice.status !== "paid";
  if (!canSend && !canVoid) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" disabled={busy} aria-label="Actions">
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {canSend && (
          <DropdownMenuItem onClick={onSend}>
            {invoice.status === "draft" ? "Send invoice" : "Resend invoice"}
          </DropdownMenuItem>
        )}
        {canVoid && (
          <DropdownMenuItem variant="destructive" onClick={onVoid}>
            Void invoice
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
