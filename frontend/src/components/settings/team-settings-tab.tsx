"use client";

import { useState } from "react";

import { CompanyInfoCard } from "@/components/settings/team/company-info-card";
import { TeamInviteForm } from "@/components/settings/team/team-invite-form";
import { TeamMemberRoleDialog } from "@/components/settings/team/team-member-role-dialog";
import { TeamMembersList } from "@/components/settings/team/team-members-list";
import { WorkspaceDetailsCard } from "@/components/settings/team/workspace-details-card";
import { InviteMemberDialog } from "@/components/workspaces/invite-member-dialog";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import type { TeamMember } from "@/lib/api/settings";
import { useWorkspace } from "@/providers/workspace-provider";

/**
 * Team & workspace settings tab.
 *
 * Pure orchestrator: composes the workspace identity, company info, members,
 * and pending-invitation cards, then routes the "invite" and "edit member"
 * actions to the appropriate dialogs. All form state lives inside child
 * components via react-hook-form.
 */
export function TeamSettingsTab() {
  const workspaceId = useWorkspaceId();
  const { currentWorkspace } = useWorkspace();

  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [selectedMember, setSelectedMember] = useState<TeamMember | null>(null);

  const canEditWorkspace =
    currentWorkspace?.role === "owner" || currentWorkspace?.role === "admin";
  const canDeleteWorkspace = currentWorkspace?.role === "owner";

  return (
    <div className="space-y-6">
      <WorkspaceDetailsCard
        workspaceId={workspaceId}
        canEditWorkspace={!!canEditWorkspace}
        canDeleteWorkspace={!!canDeleteWorkspace}
      />

      <CompanyInfoCard
        workspaceId={workspaceId}
        canEditWorkspace={!!canEditWorkspace}
      />

      <TeamMembersList
        workspaceId={workspaceId}
        canEditWorkspace={!!canEditWorkspace}
        onInvite={() => setInviteDialogOpen(true)}
        onEditMember={setSelectedMember}
      />

      {canEditWorkspace && <TeamInviteForm workspaceId={workspaceId} />}

      <InviteMemberDialog
        open={inviteDialogOpen}
        onOpenChange={setInviteDialogOpen}
        currentUserRole={currentWorkspace?.role ?? "member"}
      />

      <TeamMemberRoleDialog
        member={selectedMember}
        open={!!selectedMember}
        onOpenChange={(open) => {
          if (!open) setSelectedMember(null);
        }}
        currentUserRole={currentWorkspace?.role ?? "member"}
      />
    </div>
  );
}
