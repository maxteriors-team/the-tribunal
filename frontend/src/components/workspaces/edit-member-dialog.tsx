"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Trash2 } from "lucide-react";

import { workspacesApi } from "@/lib/api/workspaces";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Label } from "@/components/ui/label";
import { useWorkspaceId } from "@/hooks/use-workspace-id";

import { queryKeys } from "@/lib/query-keys";
interface EditMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  member: {
    id: number;
    email: string;
    full_name: string | null;
    role: string;
  };
  currentUserRole: string;
}

export function EditMemberDialog({
  open,
  onOpenChange,
  member,
  currentUserRole,
}: EditMemberDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [selectedRole, setSelectedRole] = useState<"admin" | "member">(
    member.role === "admin" ? "admin" : "member"
  );

  // Can only edit if current user is owner/admin and target is not owner
  const canEditRole = member.role !== "owner" && currentUserRole !== "member";
  const canRemove =
    member.role !== "owner" &&
    (currentUserRole === "owner" ||
      (currentUserRole === "admin" && member.role !== "admin"));

  const updateRoleMutation = useMutation({
    mutationFn: () =>
      workspacesApi.updateMemberRole(workspaceId!, member.id, selectedRole),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.team(workspaceId ?? "") });
      toast.success("Member role updated");
      onOpenChange(false);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update member role");
    },
  });

  const removeMemberMutation = useMutation({
    mutationFn: () => workspacesApi.removeMember(workspaceId!, member.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.team(workspaceId ?? "") });
      toast.success("Member removed from workspace");
      onOpenChange(false);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to remove member");
    },
  });

  const handleSave = () => {
    if (selectedRole !== member.role) {
      updateRoleMutation.mutate();
    } else {
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Edit Team Member</DialogTitle>
          <DialogDescription>
            Manage {member.full_name || member.email}&apos;s role and access.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>Email</Label>
            <p className="text-sm text-muted-foreground">{member.email}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            {member.role === "owner" ? (
              <p className="text-sm text-muted-foreground capitalize">
                {member.role} (cannot be changed)
              </p>
            ) : (
              <Select
                value={selectedRole}
                onValueChange={(value: "admin" | "member") => setSelectedRole(value)}
                disabled={!canEditRole}
              >
                <SelectTrigger id="role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">
                    <div>
                      <div className="font-medium">Member</div>
                      <div className="text-xs text-muted-foreground">
                        Can view and manage contacts, campaigns
                      </div>
                    </div>
                  </SelectItem>
                  <SelectItem value="admin">
                    <div>
                      <div className="font-medium">Admin</div>
                      <div className="text-xs text-muted-foreground">
                        Full access including team management
                      </div>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            )}
          </div>
        </div>

        <DialogFooter className="flex justify-between sm:justify-between">
          {canRemove ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="destructive"
                  disabled={removeMemberMutation.isPending}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Remove
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Remove Team Member</AlertDialogTitle>
                  <AlertDialogDescription>
                    Are you sure you want to remove {member.full_name || member.email}{" "}
                    from this workspace? They will lose access to all workspace
                    resources.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => removeMemberMutation.mutate()}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    {removeMemberMutation.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Removing...
                      </>
                    ) : (
                      "Remove Member"
                    )}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : (
            <div />
          )}
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={updateRoleMutation.isPending || !canEditRole}
            >
              {updateRoleMutation.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Save Changes
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
