"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2 } from "lucide-react";
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
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useSetMemberOnRoster, useWorkspaceRoster } from "@/hooks/useJobs";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { workspacesApi } from "@/lib/api/workspaces";
import { queryKeys } from "@/lib/query-keys";
import {
  ASSIGNABLE_ROLES,
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  type AssignableRole,
} from "@/lib/workspace-roles";
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
  // Initialise from the member's actual role (falling back to "member" only for
  // an unknown/owner value) so opening the dialog and saving never silently
  // downgrades a dispatcher, sales_rep, technician, or manager.
  const initialRole: AssignableRole = (
    ASSIGNABLE_ROLES as readonly string[]
  ).includes(member.role)
    ? (member.role as AssignableRole)
    : "member";
  const [selectedRole, setSelectedRole] = useState<AssignableRole>(initialRole);

  // Can only edit if current user is owner/admin and target is not owner
  const canEditRole = member.role !== "owner" && currentUserRole !== "member";
  // Technician writes are gated on WorkspaceManager (owner/admin/manager).
  const canManageRoster = ["owner", "admin", "manager"].includes(currentUserRole);
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

  // Dispatch tags jobs to a roster entry, not to a membership, so this is what
  // decides whether the member can be assigned work at all.
  const { data: roster, isLoading: rosterLoading } = useWorkspaceRoster(
    workspaceId ?? "",
    canManageRoster,
  );
  const rosterEntry = roster?.items.find((tech) => tech.user_id === member.id);
  const setOnRoster = useSetMemberOnRoster(workspaceId ?? "");

  const handleRosterChange = (onRoster: boolean) => {
    setOnRoster.mutate(
      {
        technicianId: rosterEntry?.id,
        userId: member.id,
        name: member.full_name || member.email.split("@")[0],
        email: member.email,
        onRoster,
      },
      {
        onSuccess: () =>
          toast.success(
            onRoster ? "Added to the job roster" : "Removed from the job roster",
          ),
        onError: (error: Error) =>
          toast.error(error.message || "Failed to update the job roster"),
      },
    );
  };

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
                onValueChange={(value: AssignableRole) => setSelectedRole(value)}
                disabled={!canEditRole}
              >
                <SelectTrigger id="role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ASSIGNABLE_ROLES.map((role) => (
                    <SelectItem key={role} value={role}>
                      <div>
                        <div className="font-medium">{ROLE_LABELS[role]}</div>
                        <div className="text-xs text-muted-foreground">
                          {ROLE_DESCRIPTIONS[role]}
                        </div>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          {canManageRoster && (
            <div className="flex items-start justify-between gap-4 rounded-md border p-3">
              <div className="space-y-1">
                <Label htmlFor="job-roster">Job roster</Label>
                <p className="text-xs text-muted-foreground">
                  Lets dispatch tag {member.full_name || "them"} to jobs. Technicians
                  are added automatically; turn this on for anyone else who works in
                  the field.
                </p>
              </div>
              <Switch
                id="job-roster"
                checked={rosterEntry?.is_active ?? false}
                onCheckedChange={handleRosterChange}
                disabled={rosterLoading || setOnRoster.isPending}
              />
            </div>
          )}
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
