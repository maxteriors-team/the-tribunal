"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  Save,
  Check,
  Loader2,
  Trash2,
  UserPlus,
  Clock,
  X,
  Mail,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { InviteMemberDialog } from "@/components/workspaces/invite-member-dialog";
import { EditMemberDialog } from "@/components/workspaces/edit-member-dialog";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { useWorkspace } from "@/providers/workspace-provider";
import { settingsApi, type TeamMember } from "@/lib/api/settings";
import { workspacesApi } from "@/lib/api/workspaces";
import { invitationsApi } from "@/lib/api/invitations";
import { TIMEZONE_OPTIONS } from "@/lib/constants";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatDate } from "@/lib/utils/date";
import { getInitialsFromName } from "@/lib/utils/initials";

export function TeamSettingsTab() {
  const workspaceId = useWorkspaceId();
  const { currentWorkspace, workspaces, setCurrentWorkspace } = useWorkspace();
  const queryClient = useQueryClient();
  const router = useRouter();

  const [workspaceSaved, setWorkspaceSaved] = useState(false);
  const [companySaved, setCompanySaved] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [editMemberDialogOpen, setEditMemberDialogOpen] = useState(false);
  const [selectedMember, setSelectedMember] = useState<TeamMember | null>(null);

  // Track workspace local edits
  const [workspaceEdits, setWorkspaceEdits] = useState<{
    name?: string;
    description?: string;
  }>({});

  // Track company info edits (stored in workspace.settings)
  const [companyEdits, setCompanyEdits] = useState<{
    business_name?: string;
    phone?: string;
    website?: string;
    address?: string;
    city?: string;
    state?: string;
    postal_code?: string;
    country?: string;
    timezone?: string;
  }>({});

  // Fetch team members
  const { data: teamMembers, isPending: teamLoading } = useQuery({
    queryKey: queryKeys.settings.team(workspaceId ?? ""),
    queryFn: () => settingsApi.getTeamMembers(workspaceId!),
    enabled: !!workspaceId,
  });

  // Fetch pending invitations (only for admins/owners)
  const isAdminOrOwner =
    currentWorkspace?.role === "owner" || currentWorkspace?.role === "admin";
  const { data: pendingInvitations, isPending: invitationsLoading } = useQuery({
    queryKey: queryKeys.invitations.bare(workspaceId ?? ""),
    queryFn: () => invitationsApi.list(workspaceId!),
    enabled: !!workspaceId && isAdminOrOwner,
  });

  // Cancel invitation mutation
  const cancelInvitationMutation = useMutation({
    mutationFn: (invitationId: string) =>
      invitationsApi.cancel(workspaceId!, invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.invitations.bare(workspaceId ?? "") });
      toast.success("Invitation cancelled");
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to cancel invitation"));
    },
  });

  // Workspace update mutation
  const workspaceUpdateMutation = useMutation({
    mutationFn: (data: { name?: string; description?: string }) =>
      workspacesApi.update(workspaceId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      setWorkspaceEdits({});
      setWorkspaceSaved(true);
      toast.success("Workspace updated successfully");
      setTimeout(() => setWorkspaceSaved(false), 2000);
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to update workspace"));
    },
  });

  // Workspace delete mutation
  const workspaceDeleteMutation = useMutation({
    mutationFn: () => workspacesApi.delete(workspaceId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      toast.success("Workspace deleted successfully");
      setDeleteDialogOpen(false);
      // Switch to another workspace if available
      const remainingWorkspaces = workspaces.filter(
        (ws) => ws.workspace.id !== workspaceId
      );
      if (remainingWorkspaces.length > 0) {
        setCurrentWorkspace(remainingWorkspaces[0].workspace.id);
      } else {
        router.push("/");
      }
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to delete workspace"));
    },
  });

  // Set default workspace mutation
  const setDefaultMutation = useMutation({
    mutationFn: () => workspacesApi.setDefault(workspaceId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      toast.success("Default workspace updated");
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to set default workspace"));
    },
  });

  // Derived workspace form values
  const workspaceForm = {
    name: workspaceEdits.name ?? currentWorkspace?.workspace.name ?? "",
    description:
      workspaceEdits.description ?? currentWorkspace?.workspace.description ?? "",
  };

  // Derived company form values (from workspace.settings)
  const workspaceSettings = currentWorkspace?.workspace.settings as
    | Record<string, unknown>
    | undefined;
  const companyForm = {
    business_name:
      companyEdits.business_name ??
      (workspaceSettings?.business_name as string) ??
      "",
    phone: companyEdits.phone ?? (workspaceSettings?.phone as string) ?? "",
    website:
      companyEdits.website ?? (workspaceSettings?.website as string) ?? "",
    address:
      companyEdits.address ?? (workspaceSettings?.address as string) ?? "",
    city: companyEdits.city ?? (workspaceSettings?.city as string) ?? "",
    state: companyEdits.state ?? (workspaceSettings?.state as string) ?? "",
    postal_code:
      companyEdits.postal_code ??
      (workspaceSettings?.postal_code as string) ??
      "",
    country:
      companyEdits.country ?? (workspaceSettings?.country as string) ?? "",
    timezone:
      companyEdits.timezone ??
      (workspaceSettings?.timezone as string) ??
      "America/New_York",
  };

  const handleSaveWorkspace = () => {
    workspaceUpdateMutation.mutate({
      name: workspaceForm.name || undefined,
      description: workspaceForm.description || undefined,
    });
  };

  // Company info update mutation
  const companyUpdateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      workspacesApi.update(workspaceId!, {
        settings: {
          ...workspaceSettings,
          ...data,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      setCompanyEdits({});
      setCompanySaved(true);
      toast.success("Company information updated successfully");
      setTimeout(() => setCompanySaved(false), 2000);
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to update company information"));
    },
  });

  const handleSaveCompany = () => {
    companyUpdateMutation.mutate({
      business_name: companyForm.business_name || undefined,
      phone: companyForm.phone || undefined,
      website: companyForm.website || undefined,
      address: companyForm.address || undefined,
      city: companyForm.city || undefined,
      state: companyForm.state || undefined,
      postal_code: companyForm.postal_code || undefined,
      country: companyForm.country || undefined,
      timezone: companyForm.timezone,
    });
  };

  const handleDeleteWorkspace = () => {
    workspaceDeleteMutation.mutate();
  };

  const canEditWorkspace =
    currentWorkspace?.role === "owner" || currentWorkspace?.role === "admin";
  const canDeleteWorkspace = currentWorkspace?.role === "owner";

  const handleEditMember = (member: TeamMember) => {
    setSelectedMember(member);
    setEditMemberDialogOpen(true);
  };

  return (
    <div className="space-y-6">
      {/* Workspace Settings Card */}
      <Card>
        <CardHeader>
          <CardTitle>Workspace Settings</CardTitle>
          <CardDescription>
            Manage your workspace details and configuration
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="workspaceName">Workspace Name</Label>
            <Input
              id="workspaceName"
              value={workspaceForm.name}
              onChange={(e) =>
                setWorkspaceEdits((prev) => ({
                  ...prev,
                  name: e.target.value,
                }))
              }
              placeholder="My Workspace"
              disabled={!canEditWorkspace}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="workspaceDescription">Description</Label>
            <Textarea
              id="workspaceDescription"
              value={workspaceForm.description}
              onChange={(e) =>
                setWorkspaceEdits((prev) => ({
                  ...prev,
                  description: e.target.value,
                }))
              }
              placeholder="A brief description of this workspace..."
              className="min-h-[80px]"
              disabled={!canEditWorkspace}
            />
          </div>
          <Separator />
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Default Workspace</Label>
              <p className="text-sm text-muted-foreground">
                Set this as your default workspace when you log in
              </p>
            </div>
            <Switch
              checked={currentWorkspace?.is_default ?? false}
              onCheckedChange={() => setDefaultMutation.mutate()}
              disabled={
                setDefaultMutation.isPending || currentWorkspace?.is_default
              }
            />
          </div>
          {!canEditWorkspace && (
            <p className="text-sm text-muted-foreground">
              Only workspace owners and admins can edit these settings.
            </p>
          )}
        </CardContent>
        <CardFooter className="flex justify-between">
          <div>
            {canEditWorkspace && (
              <Button
                onClick={handleSaveWorkspace}
                disabled={workspaceUpdateMutation.isPending}
              >
                {workspaceUpdateMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 size-4 animate-spin" />
                    Saving...
                  </>
                ) : workspaceSaved ? (
                  <>
                    <Check className="mr-2 size-4" />
                    Saved
                  </>
                ) : (
                  <>
                    <Save className="mr-2 size-4" />
                    Save Changes
                  </>
                )}
              </Button>
            )}
          </div>
          {canDeleteWorkspace && (
            <AlertDialog
              open={deleteDialogOpen}
              onOpenChange={setDeleteDialogOpen}
            >
              <AlertDialogTrigger asChild>
                <Button variant="destructive">
                  <Trash2 className="mr-2 size-4" />
                  Delete Workspace
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete Workspace</AlertDialogTitle>
                  <AlertDialogDescription>
                    Are you sure you want to delete &quot;
                    {currentWorkspace?.workspace.name}&quot;? This action cannot
                    be undone. All data including contacts, campaigns, and team
                    members will be permanently removed.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={handleDeleteWorkspace}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                    disabled={workspaceDeleteMutation.isPending}
                  >
                    {workspaceDeleteMutation.isPending ? (
                      <>
                        <Loader2 className="mr-2 size-4 animate-spin" />
                        Deleting...
                      </>
                    ) : (
                      "Delete Workspace"
                    )}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </CardFooter>
      </Card>

      {/* Company Information Card */}
      <Card>
        <CardHeader>
          <CardTitle>Company Information</CardTitle>
          <CardDescription>
            Business details for this workspace (GoHighLevel-style subaccount
            info)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="businessName">Business Name</Label>
              <Input
                id="businessName"
                value={companyForm.business_name}
                onChange={(e) =>
                  setCompanyEdits((prev) => ({
                    ...prev,
                    business_name: e.target.value,
                  }))
                }
                placeholder="Acme Inc."
                disabled={!canEditWorkspace}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="companyPhone">Phone Number</Label>
              <Input
                id="companyPhone"
                type="tel"
                value={companyForm.phone}
                onChange={(e) =>
                  setCompanyEdits((prev) => ({
                    ...prev,
                    phone: e.target.value,
                  }))
                }
                placeholder="+1 (555) 123-4567"
                disabled={!canEditWorkspace}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="companyWebsite">Website</Label>
            <Input
              id="companyWebsite"
              type="url"
              value={companyForm.website}
              onChange={(e) =>
                setCompanyEdits((prev) => ({
                  ...prev,
                  website: e.target.value,
                }))
              }
              placeholder="https://example.com"
              disabled={!canEditWorkspace}
            />
          </div>
          <Separator />
          <div className="space-y-2">
            <Label htmlFor="companyAddress">Street Address</Label>
            <Input
              id="companyAddress"
              value={companyForm.address}
              onChange={(e) =>
                setCompanyEdits((prev) => ({
                  ...prev,
                  address: e.target.value,
                }))
              }
              placeholder="123 Main Street"
              disabled={!canEditWorkspace}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="companyCity">City</Label>
              <Input
                id="companyCity"
                value={companyForm.city}
                onChange={(e) =>
                  setCompanyEdits((prev) => ({
                    ...prev,
                    city: e.target.value,
                  }))
                }
                placeholder="San Francisco"
                disabled={!canEditWorkspace}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="companyState">State / Province</Label>
              <Input
                id="companyState"
                value={companyForm.state}
                onChange={(e) =>
                  setCompanyEdits((prev) => ({
                    ...prev,
                    state: e.target.value,
                  }))
                }
                placeholder="CA"
                disabled={!canEditWorkspace}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="companyPostalCode">Postal Code</Label>
              <Input
                id="companyPostalCode"
                value={companyForm.postal_code}
                onChange={(e) =>
                  setCompanyEdits((prev) => ({
                    ...prev,
                    postal_code: e.target.value,
                  }))
                }
                placeholder="94105"
                disabled={!canEditWorkspace}
              />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="companyCountry">Country</Label>
              <Input
                id="companyCountry"
                value={companyForm.country}
                onChange={(e) =>
                  setCompanyEdits((prev) => ({
                    ...prev,
                    country: e.target.value,
                  }))
                }
                placeholder="United States"
                disabled={!canEditWorkspace}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="companyTimezone">Timezone</Label>
              <Select
                value={companyForm.timezone}
                onValueChange={(value) =>
                  setCompanyEdits((prev) => ({ ...prev, timezone: value }))
                }
                disabled={!canEditWorkspace}
              >
                <SelectTrigger id="companyTimezone">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIMEZONE_OPTIONS.map((tz) => (
                    <SelectItem key={tz.value} value={tz.value}>
                      {tz.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          {!canEditWorkspace && (
            <p className="text-sm text-muted-foreground">
              Only workspace owners and admins can edit company information.
            </p>
          )}
        </CardContent>
        <CardFooter>
          {canEditWorkspace && (
            <Button
              onClick={handleSaveCompany}
              disabled={companyUpdateMutation.isPending}
            >
              {companyUpdateMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Saving...
                </>
              ) : companySaved ? (
                <>
                  <Check className="mr-2 size-4" />
                  Saved
                </>
              ) : (
                <>
                  <Save className="mr-2 size-4" />
                  Save Company Info
                </>
              )}
            </Button>
          )}
        </CardFooter>
      </Card>

      {/* Team Members Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Team Members</CardTitle>
              <CardDescription>
                Manage who has access to your workspace
              </CardDescription>
            </div>
            {canEditWorkspace && (
              <Button onClick={() => setInviteDialogOpen(true)}>
                <UserPlus className="mr-2 size-4" />
                Invite Member
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {teamLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : teamMembers && teamMembers.length > 0 ? (
            teamMembers.map((member) => (
              <div
                key={member.id}
                className="flex items-center justify-between p-3 rounded-lg border"
              >
                <div className="flex items-center gap-3">
                  <div className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-sm font-medium">
                    {getInitialsFromName(member.full_name, member.email)}
                  </div>
                  <div>
                    <p className="font-medium">
                      {member.full_name || member.email}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {member.email}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Badge variant="outline" className="capitalize">
                    {member.role}
                  </Badge>
                  {canEditWorkspace && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleEditMember(member)}
                    >
                      Edit
                    </Button>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              No team members found
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pending Invitations Card */}
      {canEditWorkspace && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="size-5" />
              Pending Invitations
            </CardTitle>
            <CardDescription>
              Invitations waiting to be accepted
            </CardDescription>
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
                        Invited{" "}
                        {formatDate(invitation.created_at)}
                        {" · "}
                        Expires{" "}
                        {formatDate(invitation.expires_at)}
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
                      onClick={() =>
                        cancelInvitationMutation.mutate(invitation.id)
                      }
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
      )}

      {/* Invite Member Dialog */}
      <InviteMemberDialog
        open={inviteDialogOpen}
        onOpenChange={setInviteDialogOpen}
      />

      {/* Edit Member Dialog */}
      {selectedMember && (
        <EditMemberDialog
          open={editMemberDialogOpen}
          onOpenChange={setEditMemberDialogOpen}
          member={selectedMember}
          currentUserRole={currentWorkspace?.role ?? "member"}
        />
      )}
    </div>
  );
}
