"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, CreditCard, Loader2, Trash2 } from "lucide-react";
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
import { paymentMethodsApi } from "@/lib/api/payment-methods";
import { queryKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { PaymentMethod } from "@/types/payment-method";

/** "Visa 4242" — display metadata only; never a card number. */
function cardLabel(method: PaymentMethod): string {
  const brand = method.brand
    ? method.brand.charAt(0).toUpperCase() + method.brand.slice(1)
    : "Card";
  return method.last4 ? `${brand} \u2022\u2022\u2022\u2022 ${method.last4}` : brand;
}

function expiryLabel(method: PaymentMethod): string | null {
  if (!method.exp_month || !method.exp_year) return null;
  return `Expires ${String(method.exp_month).padStart(2, "0")}/${method.exp_year}`;
}

/**
 * Cards this customer has authorized us to keep and charge later.
 *
 * The operator can see what is on file and send a link, but there is no field
 * here to type a card into. That is deliberate: an operator keying a customer's
 * card is a card-not-present transaction with worse decline rates and higher
 * fraud exposure, and the consent record would be the operator ticking a box on
 * the customer's behalf rather than the customer's own act.
 */
export function ContactPaymentMethods({
  workspaceId,
  contactId,
}: {
  workspaceId: string | null;
  contactId: number;
}) {
  const queryClient = useQueryClient();
  const [pendingRemoval, setPendingRemoval] = useState<PaymentMethod | null>(
    null
  );

  const { data: methods, isPending } = useQuery({
    queryKey: queryKeys.contacts.paymentMethods(workspaceId ?? "", contactId),
    queryFn: () => paymentMethodsApi.list(workspaceId!, contactId),
    enabled: !!workspaceId,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.contacts.paymentMethods(workspaceId ?? "", contactId),
    });

  const setupLink = useMutation({
    mutationFn: () => paymentMethodsApi.createSetupLink(workspaceId!, contactId),
    onSuccess: async (link) => {
      // The link is single-use and expires, so it is copied for the operator to
      // send rather than displayed for someone to bookmark.
      try {
        await navigator.clipboard.writeText(link.url);
        toast.success("Card-on-file link copied", {
          description: `Send it to the customer. It expires ${formatDate(link.expires_at)} and can only be used once.`,
        });
      } catch {
        // Clipboard can be blocked; the link is still useless to us unsent.
        toast.success("Card-on-file link created", { description: link.url });
      }
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Could not create the link."));
    },
  });

  const remove = useMutation({
    mutationFn: (methodId: string) =>
      paymentMethodsApi.remove(workspaceId!, contactId, methodId),
    onSuccess: async () => {
      setPendingRemoval(null);
      await invalidate();
      toast.success("Card removed");
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Could not remove that card."));
    },
  });

  const setDefault = useMutation({
    mutationFn: (methodId: string) =>
      paymentMethodsApi.setDefault(workspaceId!, contactId, methodId),
    onSuccess: async () => {
      await invalidate();
      toast.success("Default card updated");
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Could not update the default."));
    },
  });

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground px-2">
        Payment method
      </h3>

      {isPending ? (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      ) : !methods?.length ? (
        <p className="text-xs text-muted-foreground px-2 py-2">
          No card on file. Send a link and the customer enters their own card.
        </p>
      ) : (
        <div className="space-y-2 px-2">
          {methods.map((method) => (
            <div
              key={method.id}
              className="flex items-center gap-2 p-2 rounded-lg bg-muted/30 text-xs"
            >
              <CreditCard className="h-3 w-3 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{cardLabel(method)}</p>
                <p className="text-muted-foreground text-xs">
                  {expiryLabel(method) ??
                    `Saved ${formatDate(method.created_at)}`}
                </p>
              </div>
              {method.is_default ? (
                <Badge variant="secondary" className="text-xs py-0">
                  Default
                </Badge>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 text-xs px-2"
                  disabled={setDefault.isPending}
                  onClick={() => setDefault.mutate(method.id)}
                >
                  Make default
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                title={`Remove ${cardLabel(method)}`}
                aria-label={`Remove ${cardLabel(method)}`}
                onClick={() => setPendingRemoval(method)}
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          ))}
        </div>
      )}

      <div className="px-2">
        <Button
          variant="outline"
          size="sm"
          className="w-full text-xs"
          disabled={!workspaceId || setupLink.isPending}
          onClick={() => setupLink.mutate()}
        >
          {setupLink.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {methods?.length ? "Send another card link" : "Send card-on-file link"}
        </Button>
      </div>

      <AlertDialog
        open={pendingRemoval !== null}
        onOpenChange={(open) => !open && setPendingRemoval(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Remove {pendingRemoval ? cardLabel(pendingRemoval) : "this card"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The card is detached at Stripe and can no longer be charged. Any
              automatic charges set up against it will stop, and the customer
              would have to save a new card. Payments already taken are
              unaffected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep card</AlertDialogCancel>
            <AlertDialogAction
              disabled={remove.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (pendingRemoval) remove.mutate(pendingRemoval.id);
              }}
            >
              {remove.isPending ? "Removing\u2026" : "Remove card"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
