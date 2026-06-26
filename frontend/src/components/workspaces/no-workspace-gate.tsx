"use client";

import { Building2, Plus } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { CreateWorkspaceDialog } from "@/components/workspaces/create-workspace-dialog";
import { useWorkspace } from "@/providers/workspace-provider";

/**
 * Belt-and-suspenders for finding RF-001: if the authenticated user has zero
 * workspaces (e.g. an account created before auto-provisioning), every
 * workspace-scoped page would otherwise freeze on its loading skeleton because
 * queries gate on `enabled: !!workspaceId`. Render an actionable "create your
 * workspace" gate instead of an infinite spinner.
 */
export function NoWorkspaceGate({ children }: { children: ReactNode }) {
  const { workspaces, isPending } = useWorkspace();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  if (isPending || workspaces.length > 0) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-6 px-6 py-16 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-yellow-400 to-amber-500 text-black shadow-sm">
        <Building2 className="size-7" />
      </div>
      <div className="max-w-md space-y-2">
        <h1 className="text-2xl font-semibold">Create your workspace</h1>
        <p className="text-muted-foreground">
          You don&apos;t belong to a workspace yet. Create one to start capturing
          leads, running campaigns, and booking appointments.
        </p>
      </div>
      <Button size="lg" onClick={() => setCreateDialogOpen(true)}>
        <Plus className="size-4" />
        Create workspace
      </Button>

      <CreateWorkspaceDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />
    </div>
  );
}
