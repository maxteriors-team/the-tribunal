"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Loader2, Mail, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { invitationsApi } from "@/lib/api/invitations";
import { queryKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface TeamInviteFormProps {
  workspaceId: string | null;
}

/**
 * Pending invitations card.
 *
 * Renders the list of outstanding workspace invitations and exposes a per-row
 * cancel action. The "send invitation" form itself lives in
 * `InviteMemberDialog` (already RHF-driven); this component focuses purely on
 * the pending-list surface so TeamSettingsTab stays small.
 */
export function TeamInviteForm({ workspaceId }: TeamInviteFormProps) {
  const queryClient = useQueryClient();

  const { data: pendingInvitations, isPending: invitationsLoading } = useQuery({
    queryKey: queryKeys.invitations.all(workspaceId ?? ""),
    queryFn: () => invitationsApi.list(workspaceId!),
    enabled: !!workspaceId,
  });

  const cancelInvitationMutation = useMutation({
    mutationFn: (invitationId: string) =>
      invitationsApi.cancel(workspaceId!, invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.invitations.all(workspaceId ?? ""),
      });
      toast.success("Invitation cancelled");
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to cancel invitation"));
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="size-5" />
          Pending Invitations
        </CardTitle>
        <CardDescription>Invitations waiting to be accepted</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {invitationsLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : pendingInvitations && pendingInvitations.length > 0 ? (
          pendingInvitations.map((invitation) => (
            <div
              key={invitation.id}
              className="flex items-center justify-between p-3 rounded-lg border"
            >
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-full bg-yellow-500/10 text-sm font-medium text-yellow-500">
                  <Mail className="size-5" />
                </div>
                <div>
                  <p className="font-medium">{invitation.email}</p>
                  <p className="text-sm text-muted-foreground">
                    Invited {formatDate(invitation.created_at)}
                    {" · "}
                    Expires {formatDate(invitation.expires_at)}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Badge variant="outline" className="capitalize">
                  {invitation.role}
                </Badge>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => cancelInvitationMutation.mutate(invitation.id)}
                  disabled={cancelInvitationMutation.isPending}
                >
                  <X className="size-4" />
                </Button>
              </div>
            </div>
          ))
        ) : (
          <div className="text-center py-8 text-muted-foreground">
            No pending invitations
          </div>
        )}
      </CardContent>
    </Card>
  );
}
