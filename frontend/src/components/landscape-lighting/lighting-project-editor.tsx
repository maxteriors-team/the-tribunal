"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { AlertTriangle, ArrowLeft, CheckCircle2, Cloud, Loader2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useId, useState } from "react";

import { LightDesigner } from "@/components/estimator/light-designer";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { lightingProjectsApi, type LightingProjectDetail } from "@/lib/api/lighting-projects";
import type { LandscapeWorkflowTab } from "@/lib/estimator/types";
import { queryKeys } from "@/lib/query-keys";
import { STATIC } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useWorkspace } from "@/providers/workspace-provider";

import { ProjectWorkflowTabs } from "./studio/project-workflow-tabs";
import { useLightingProjectAutosave } from "./use-lighting-project-autosave";

interface LightingProjectEditorProps {
  projectId: string;
}

const projectTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function responseStatus(error: unknown): number | null {
  return isAxiosError(error) ? (error.response?.status ?? null) : null;
}

function ProjectNameField({
  project,
  onSave,
}: {
  project: LightingProjectDetail;
  onSave: (name: string) => Promise<void>;
}) {
  const inputId = useId();
  const [name, setName] = useState(project.name);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Project name is required.");
      return;
    }
    if (trimmed === project.name) {
      setName(project.name);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(trimmed);
    } catch (saveError) {
      setError(getApiErrorMessage(saveError, "Project name could not be saved."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-w-0 flex-1">
      <label htmlFor={inputId} className="sr-only">
        Project name
      </label>
      <div className="flex min-w-0 items-center gap-2">
        <Input
          id={inputId}
          value={name}
          maxLength={200}
          disabled={saving}
          title="Edit project name"
          onChange={(event) => setName(event.target.value)}
          onBlur={() => void save()}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              setName(project.name);
              setError(null);
              event.currentTarget.blur();
            }
          }}
          className="h-8 min-w-0 max-w-lg rounded-none border-0 bg-transparent px-1 text-[15px] font-semibold text-[#1b1a18] shadow-none hover:bg-black/[0.03] focus-visible:ring-2 focus-visible:ring-[#8a682f] focus-visible:ring-offset-1 disabled:opacity-60"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${inputId}-error` : undefined}
        />
        {saving ? (
          <Loader2
            className="size-3.5 shrink-0 animate-spin text-[#6b675f] motion-reduce:animate-none"
            aria-label="Saving project name"
          />
        ) : null}
      </div>
      {error ? (
        <p id={`${inputId}-error`} className="px-1 text-xs text-[#9f201b]" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function SaveStatus({
  status,
  label,
  errorMessage,
  onRetry,
}: {
  status: ReturnType<typeof useLightingProjectAutosave>["status"];
  label: string;
  errorMessage: string | null;
  onRetry: () => void;
}) {
  const Icon =
    status === "saved"
      ? CheckCircle2
      : status === "error" || status === "conflict"
        ? AlertTriangle
        : status === "saving" || status === "loading"
          ? Loader2
          : Cloud;
  const statusIsQuiet = status === "saved";

  return (
    <div
      className={
        statusIsQuiet
          ? "sr-only items-center gap-2 text-xs text-[#68635b] md:not-sr-only md:flex"
          : "order-3 flex w-full items-center justify-end gap-2 text-xs text-[#68635b] sm:order-none sm:w-auto"
      }
    >
      <span
        className="inline-flex min-h-6 items-center gap-1.5 whitespace-nowrap"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        title={errorMessage ?? label}
      >
        <Icon
          className={`size-3.5 ${status === "saving" || status === "loading" ? "animate-spin motion-reduce:animate-none" : ""}`}
          aria-hidden="true"
        />
        {label}
      </span>
      {status === "error" ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 border-[#b9b2a6] bg-transparent px-2 text-[#1b1a18] hover:bg-black/[0.04]"
          onClick={onRetry}
        >
          <RotateCcw className="size-3.5" aria-hidden="true" />
          Retry sync
        </Button>
      ) : null}
    </div>
  );
}

function ActiveProjectEditor({
  workspaceId,
  workspaceName,
  loadedProject,
}: {
  workspaceId: string;
  workspaceName: string;
  loadedProject: LightingProjectDetail;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [closedConflictKey, setClosedConflictKey] = useState<string | null>(null);
  const [resolvingConflict, setResolvingConflict] = useState<"load" | "copy" | null>(null);
  const [workflowTab, setWorkflowTab] = useState<LandscapeWorkflowTab>(
    loadedProject.document.activeWorkflowTab ?? "drawing",
  );
  const autosave = useLightingProjectAutosave({
    workspaceId,
    project: loadedProject,
    onCopyCreated: (copy) => router.push(`/landscape-lighting/${copy.id}`),
  });
  const selectInstallationShot = useCallback(
    async (shotId: string) => {
      const synced = await autosave.saveNow();
      const updated = await lightingProjectsApi.update(workspaceId, synced.id, {
        expected_version: synced.version,
        installation_shot_id: shotId,
      });
      queryClient.setQueryData(queryKeys.lightingProjects.detail(workspaceId, synced.id), updated);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.lightingProjects.all(workspaceId),
        refetchType: "inactive",
      });
    },
    [autosave, queryClient, workspaceId],
  );

  if (!autosave.isReady) {
    return (
      <PageLoadingState className="h-full" message="Checking this device for pending work..." />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <header
        className="ll-project-header shrink-0 border-b border-[#d8d3c9] bg-[#f8f7f4] text-[#1b1a18]"
        aria-label="Lighting project details"
      >
        <div className="mx-auto flex min-h-[50px] w-full max-w-[1800px] flex-wrap items-center gap-x-2 gap-y-1 px-2 py-1 sm:flex-nowrap sm:px-4">
          <SidebarTrigger
            className="size-7 shrink-0 text-[#4f4b44] hover:bg-black/[0.05] hover:text-[#1b1a18]"
            aria-label="Open CRM navigation"
          />
          <Link
            href="/landscape-lighting"
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-sm px-1 text-xs font-medium text-[#38352f] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#8a682f]"
          >
            <ArrowLeft className="size-3.5" aria-hidden="true" />
            Projects
          </Link>
          <span className="h-4 w-px shrink-0 bg-[#d0aa68]" aria-hidden="true" />
          <ProjectNameField
            key={`${autosave.project.id}-${autosave.project.version}`}
            project={autosave.project}
            onSave={autosave.updateProjectName}
          />
          <SaveStatus
            status={autosave.status}
            label={autosave.statusLabel}
            errorMessage={autosave.errorMessage}
            onRetry={autosave.retry}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 shrink-0 rounded-md border-[#d8d1c5] bg-transparent px-3 text-[10px] font-bold uppercase tracking-[0.12em] text-[#1b1a18] hover:bg-black/[0.04]"
            onClick={() => setWorkflowTab("proposal")}
          >
            Send proposal
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-8 shrink-0 rounded-md bg-[#191815] px-4 text-[10px] font-bold uppercase tracking-[0.12em] text-white hover:bg-black disabled:bg-[#716d65]"
            disabled={autosave.status === "saving" || autosave.status === "loading"}
            onClick={() => void autosave.saveNow()}
          >
            Save
          </Button>
          {autosave.conflict ? (
            <Dialog
              open={
                closedConflictKey !==
                `${autosave.conflict.currentVersion}-${autosave.conflict.updatedAt}`
              }
              onOpenChange={(open) =>
                setClosedConflictKey(
                  open
                    ? null
                    : `${autosave.conflict?.currentVersion}-${autosave.conflict?.updatedAt}`,
                )
              }
            >
              <DialogTrigger asChild>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 shrink-0 border-[#b9b2a6] bg-transparent text-[#1b1a18] hover:bg-black/[0.04]"
                >
                  Review conflict
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Choose which lighting plan to keep</DialogTitle>
                  <DialogDescription>
                    Another save reached Tribunal before this device. Nothing was overwritten. Load
                    the current Tribunal plan, or preserve this device&apos;s drawing as a separate
                    customer project.
                  </DialogDescription>
                </DialogHeader>
                <div className="rounded-md border p-3 text-sm">
                  <p className="font-medium">Tribunal version {autosave.conflict.currentVersion}</p>
                  <p className="mt-1 text-muted-foreground">
                    Updated {projectTimeFormatter.format(new Date(autosave.conflict.updatedAt))}
                    {autosave.conflict.updaterName ? ` by ${autosave.conflict.updaterName}` : ""}
                  </p>
                </div>
                {autosave.errorMessage ? (
                  <p className="text-sm text-destructive" role="alert">
                    {autosave.errorMessage}
                  </p>
                ) : null}
                <DialogFooter className="sm:justify-between">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={resolvingConflict !== null}
                    onClick={() => {
                      setResolvingConflict("load");
                      void autosave.loadTribunalVersion().finally(() => setResolvingConflict(null));
                    }}
                  >
                    {resolvingConflict === "load" ? (
                      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    ) : null}
                    Load Tribunal version
                  </Button>
                  <Button
                    type="button"
                    disabled={resolvingConflict !== null}
                    onClick={() => {
                      setResolvingConflict("copy");
                      void autosave.saveWorkAsCopy().finally(() => setResolvingConflict(null));
                    }}
                  >
                    {resolvingConflict === "copy" ? (
                      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    ) : null}
                    Save my work as a copy
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          ) : null}
        </div>
      </header>
      <ProjectWorkflowTabs value={workflowTab} onChange={setWorkflowTab} />

      <div
        id={`landscape-panel-${workflowTab}`}
        role="tabpanel"
        aria-labelledby={`landscape-tab-${workflowTab}`}
        className="mx-auto min-h-0 w-full max-w-[1800px] flex-1 overflow-hidden"
      >
        <LightDesigner
          key={`${autosave.project.id}-${autosave.resetKey}`}
          workspaceId={workspaceId}
          workspaceName={workspaceName}
          focus="landscape"
          landscapeProject={{
            initialDraft: autosave.initialDraft,
            onLandscapeDraftChange: autosave.onDraftChange,
            persistenceStatus: {
              state: autosave.status,
              label: autosave.statusLabel,
            },
            projectId: autosave.project.id,
            projectName: autosave.project.name,
            contactName: autosave.project.contact_name,
            contactId: autosave.project.contact_id,
            opportunityId: autosave.project.opportunity_id,
            serviceLocationId: autosave.project.service_location_id,
            installationShotId: autosave.project.installation_shot_id,
            onSelectInstallationShot: selectInstallationShot,
            flushBeforeProposal: autosave.saveNow,
            resetKey: autosave.resetKey,
            activeWorkflowTab: workflowTab,
            onActiveWorkflowTabChange: setWorkflowTab,
          }}
        />
      </div>
    </div>
  );
}

export function LightingProjectEditor({ projectId }: LightingProjectEditorProps) {
  const { currentWorkspace, currentWorkspaceId, isPending: workspacePending } = useWorkspace();
  const projectQuery = useQuery({
    queryKey: queryKeys.lightingProjects.detail(currentWorkspaceId ?? "", projectId),
    queryFn: () => lightingProjectsApi.get(currentWorkspaceId!, projectId),
    enabled: Boolean(currentWorkspaceId),
    ...STATIC,
  });

  if (workspacePending) {
    return <PageLoadingState className="h-full" message="Opening the workspace..." />;
  }
  if (!currentWorkspaceId) {
    return (
      <PageEmptyState
        className="h-full"
        title="Choose a workspace"
        description="Select a workspace before opening this lighting project."
      />
    );
  }
  if (projectQuery.isPending) {
    return <PageLoadingState className="h-full" message="Loading the lighting project..." />;
  }
  if (projectQuery.isError) {
    const status = responseStatus(projectQuery.error);
    return (
      <PageErrorState
        className="h-full"
        message={
          status === 404
            ? "This lighting project was not found in the selected workspace."
            : status === 403
              ? "You do not have access to this lighting project."
              : "The lighting project could not be loaded."
        }
        onRetry={status === 403 || status === 404 ? undefined : () => projectQuery.refetch()}
      />
    );
  }

  if (projectQuery.data.status === "archived") {
    return (
      <main className="h-full overflow-y-auto" aria-label="Archived lighting project">
        <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <Button asChild variant="ghost" size="sm" className="mb-4">
            <Link href="/landscape-lighting">
              <ArrowLeft className="size-4" aria-hidden="true" />
              Lighting projects
            </Link>
          </Button>
          <PageEmptyState
            title="Archived project is read only"
            description={`${projectQuery.data.name} remains recoverable. Restore it from the Archived project list before editing the drawing.`}
          />
        </div>
      </main>
    );
  }

  return (
    <ActiveProjectEditor
      workspaceId={currentWorkspaceId}
      workspaceName={currentWorkspace?.workspace.name ?? "Maxteriors"}
      loadedProject={projectQuery.data}
    />
  );
}
