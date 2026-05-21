"use client";

import { Check, X, Clock, Loader2 } from "lucide-react";

import {
  isOutboundWorkflowAction,
  OutboundWorkflowCard,
} from "@/components/assistant/outbound-workflow-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatRelative } from "@/lib/utils/date";
import type { PendingAction } from "@/types/pending-action";

const URGENCY_STYLES: Record<string, string> = {
  high: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  low: "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200",
};

const ACTION_TYPE_STYLES: Record<string, string> = {
  book_appointment: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  send_sms: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  enroll_campaign: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  apply_tag: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200",
};

const ACTION_TYPE_LABELS: Record<string, string> = {
  book_appointment: "Book Appointment",
  send_sms: "Send SMS",
  enroll_campaign: "Enroll Campaign",
  apply_tag: "Apply Tag",
};

function getStatusBadge(status: string) {
  switch (status) {
    case "pending":
      return <Badge variant="outline">Pending</Badge>;
    case "approved":
      return (
        <Badge variant="default" className="bg-green-600">
          Approved
        </Badge>
      );
    case "rejected":
      return <Badge variant="destructive">Rejected</Badge>;
    case "expired":
      return <Badge variant="secondary">Expired</Badge>;
    case "executed":
      return (
        <Badge variant="default" className="bg-blue-600">
          Executed
        </Badge>
      );
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
    default:
      return <Badge variant="secondary">{status}</Badge>;
  }
}

interface PendingActionCardProps {
  action: PendingAction;
  onApprove: () => void;
  onReject: () => void;
  isApproving: boolean;
  isRejecting: boolean;
}

export function PendingActionCard({
  action,
  onApprove,
  onReject,
  isApproving,
  isRejecting,
}: PendingActionCardProps) {
  const isPending = action.status === "pending";

  if (isOutboundWorkflowAction(action)) {
    return (
      <OutboundWorkflowCard
        action={action}
        onApprove={onApprove}
        onReject={onReject}
        isApproving={isApproving}
        isRejecting={isRejecting}
      />
    );
  }

  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
          <Clock className="h-5 w-5 text-muted-foreground" />
        </div>

        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="font-medium leading-tight">{action.description}</h3>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Badge
                className={cn(
                  "text-xs",
                  ACTION_TYPE_STYLES[action.action_type] || "bg-gray-100 text-gray-800"
                )}
              >
                {ACTION_TYPE_LABELS[action.action_type] || action.action_type}
              </Badge>
              <Badge className={cn("text-xs", URGENCY_STYLES[action.urgency] || URGENCY_STYLES.low)}>
                {action.urgency}
              </Badge>
              {getStatusBadge(action.status)}
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>
              Created{" "}
              {formatRelative(action.created_at)}
            </span>
            {action.expires_at && (
              <span>
                Expires{" "}
                {formatRelative(action.expires_at)}
              </span>
            )}
            {action.rejection_reason && (
              <span className="italic">Reason: {action.rejection_reason}</span>
            )}
          </div>
        </div>

        {isPending && (
          <div className="flex shrink-0 items-center gap-1">
            <Button
              size="sm"
              onClick={onApprove}
              disabled={isApproving || isRejecting}
              className="bg-green-600 hover:bg-green-700"
            >
              {isApproving ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="mr-1 h-3.5 w-3.5" />
              )}
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={onReject}
              disabled={isApproving || isRejecting}
              className="text-destructive"
            >
              {isRejecting ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <X className="mr-1 h-3.5 w-3.5" />
              )}
              Reject
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
