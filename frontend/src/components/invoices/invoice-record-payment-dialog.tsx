"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { invoicesApi } from "@/lib/api/invoices";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Invoice, ManualInvoicePaymentMethod } from "@/types";

interface InvoiceRecordPaymentDialogProps {
  invoice: Invoice | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function InvoiceRecordPaymentDialog({
  invoice,
  open,
  onOpenChange,
}: InvoiceRecordPaymentDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const remaining = Math.max(0, (invoice?.total ?? 0) - (invoice?.amount_paid ?? 0));
  const [paymentMethod, setPaymentMethod] = useState<ManualInvoicePaymentMethod>("check");
  const [amount, setAmount] = useState(() => remaining.toFixed(2));
  const [reference, setReference] = useState("");
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const paymentAmount = Number(amount);
  const balanceAfter = Math.max(
    0,
    remaining - (Number.isFinite(paymentAmount) ? paymentAmount : 0),
  );
  const amountIsValid = paymentAmount > 0 && paymentAmount <= remaining;

  const mutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !invoice || !idempotencyKey) {
        throw new Error("No invoice selected");
      }
      return invoicesApi.recordManualPayment(workspaceId, invoice.id, {
        payment_method: paymentMethod,
        amount: paymentAmount,
        reference: paymentMethod === "check" ? reference.trim() || null : null,
        idempotency_key: idempotencyKey,
      });
    },
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.invoices.all(workspaceId ?? ""),
      });
      toast.success(
        `${paymentMethod === "check" ? "Check" : "Cash"} payment recorded for ${updated.number}`,
      );
      onOpenChange(false);
    },
    onError: (error: unknown) => {
      toast.error(getApiErrorMessage(error, "Could not record the payment"));
    },
  });

  const handleOpenChange = (next: boolean) => {
    if (!next && mutation.isPending) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Record payment</DialogTitle>
          <DialogDescription>
            Record a deposit, partial payment, or final payment for {invoice?.number}. A branded
            receipt is queued for every payment.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-md border bg-muted/40 p-3">
            <p className="text-sm text-muted-foreground">Remaining balance</p>
            <p className="text-xl font-semibold">
              {formatCurrency(remaining, invoice?.currency ?? "USD")}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="invoice-payment-amount">Payment amount</Label>
            <Input
              id="invoice-payment-amount"
              type="number"
              inputMode="decimal"
              min="0.01"
              max={remaining}
              step="0.01"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
            {amountIsValid && balanceAfter > 0 && (
              <p className="text-xs text-muted-foreground">
                Invoice remains partial with{" "}
                {formatCurrency(balanceAfter, invoice?.currency ?? "USD")} due.
              </p>
            )}
            {amount !== "" && !amountIsValid && (
              <p className="text-xs text-destructive">
                Enter an amount between $0.01 and the remaining balance.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="invoice-payment-method">Payment method</Label>
            <Select
              value={paymentMethod}
              onValueChange={(value) => setPaymentMethod(value as ManualInvoicePaymentMethod)}
            >
              <SelectTrigger id="invoice-payment-method" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="check">Check</SelectItem>
                <SelectItem value="cash">Cash</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {paymentMethod === "check" && (
            <div className="space-y-2">
              <Label htmlFor="invoice-payment-reference">Check number (optional)</Label>
              <Input
                id="invoice-payment-reference"
                value={reference}
                onChange={(event) => setReference(event.target.value)}
                maxLength={100}
                placeholder="e.g. 1042"
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !amountIsValid || !idempotencyKey}
          >
            {mutation.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Record {paymentMethod} payment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
