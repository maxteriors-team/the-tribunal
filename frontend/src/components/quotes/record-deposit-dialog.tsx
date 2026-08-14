"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2 } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { quotesApi } from "@/lib/api/quotes";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { ManualDepositPaymentMethod, Quote } from "@/types";

const PAYMENT_METHODS: Array<{
  value: ManualDepositPaymentMethod;
  label: string;
  description: string;
}> = [
  { value: "cash", label: "Cash", description: "Cash received directly" },
  { value: "check", label: "Check", description: "Paper or cashier's check received" },
  { value: "other", label: "Other", description: "Another offline payment method" },
];

export function depositPaymentMethodLabel(method?: Quote["deposit_payment_method"]): string | null {
  if (!method) return null;
  if (method === "card") return "Credit card";
  return PAYMENT_METHODS.find((option) => option.value === method)?.label ?? null;
}

interface RecordDepositDialogProps {
  workspaceId: string;
  quote: Quote;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RecordDepositDialog({
  workspaceId,
  quote,
  open,
  onOpenChange,
}: RecordDepositDialogProps) {
  const queryClient = useQueryClient();
  const [paymentMethod, setPaymentMethod] = useState<ManualDepositPaymentMethod>("cash");
  const amount = formatCurrency(quote.deposit_amount ?? 0, quote.currency);

  const recordMutation = useMutation({
    mutationFn: () => quotesApi.recordDeposit(workspaceId, quote.id, paymentMethod),
    onSuccess: (updatedQuote) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.quotes.all(workspaceId) });
      const recordedMethod = depositPaymentMethodLabel(updatedQuote.deposit_payment_method);
      if (updatedQuote.deposit_payment_method === "card") {
        toast.success("Deposit was already paid by credit card");
      } else {
        toast.success(`${recordedMethod ?? "Offline"} deposit recorded`);
      }
      setPaymentMethod("cash");
      onOpenChange(false);
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Failed to record deposit")),
  });

  const handleOpenChange = (nextOpen: boolean) => {
    if (recordMutation.isPending) return;
    if (!nextOpen) setPaymentMethod("cash");
    onOpenChange(nextOpen);
  };

  const selectedMethodLabel =
    PAYMENT_METHODS.find((option) => option.value === paymentMethod)?.label ?? "Offline";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Record deposit</DialogTitle>
          <DialogDescription>
            Choose how you received the {amount} deposit for {quote.number}.
          </DialogDescription>
        </DialogHeader>

        <RadioGroup
          value={paymentMethod}
          onValueChange={(value) => setPaymentMethod(value as ManualDepositPaymentMethod)}
          className="gap-2"
          aria-label="Deposit payment method"
        >
          {PAYMENT_METHODS.map((option) => (
            <Label
              key={option.value}
              htmlFor={`deposit-method-${option.value}`}
              className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 hover:bg-muted/50 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5"
            >
              <RadioGroupItem value={option.value} id={`deposit-method-${option.value}`} />
              <span className="grid gap-0.5 font-normal">
                <span className="font-medium">{option.label}</span>
                <span className="text-xs text-muted-foreground">{option.description}</span>
              </span>
            </Label>
          ))}
        </RadioGroup>

        <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>
            Continue only after the money is received. This completes the deposit and closes any
            open credit-card checkout link. It cannot be undone here.
          </p>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={recordMutation.isPending}
          >
            Cancel
          </Button>
          <Button onClick={() => recordMutation.mutate()} disabled={recordMutation.isPending}>
            {recordMutation.isPending && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            )}
            Record {selectedMethodLabel.toLowerCase()} deposit
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
