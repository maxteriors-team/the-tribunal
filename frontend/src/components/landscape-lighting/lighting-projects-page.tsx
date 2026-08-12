"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Archive,
  ArchiveRestore,
  ArrowRight,
  FolderOpen,
  Loader2,
  Plus,
  Search,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
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
import { Input } from "@/components/ui/input";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { contactsApi } from "@/lib/api/contacts";
import {
  lightingProjectsApi,
  type LightingProjectDetail,
  type LightingProjectSummary,
} from "@/lib/api/lighting-projects";
import {
  deleteLandscapeDraft,
  loadLandscapeDraft,
  type LandscapeDraft,
} from "@/lib/estimator/landscape-draft";
import { queryKeys } from "@/lib/query-keys";
import { POLL_30S, STATIC } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Contact } from "@/types";

interface LightingProjectsPageProps {
  workspaceId: string;
}

type ProjectFilter = "active" | "archived";
type CreateMode = "create" | "recover";

const projectTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function contactLabel(contact: Contact): string {
  const name = [contact.first_name, contact.last_name].filter(Boolean).join(" ");
  return name || contact.company_name || contact.email || `Contact ${contact.id}`;
}

function DraftCreateDialog({
  workspaceId,
  mode,
  browserDraft,
  onOpenChange,
}: {
  workspaceId: string;
  mode: CreateMode;
  browserDraft: LandscapeDraft | null | undefined;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchId = useId();
  const nameId = useId();
  const [name, setName] = useState(
    mode === "recover" ? "Recovered landscape lighting plan" : "",
  );
  const [contactSearch, setContactSearch] = useState("");
  const [debouncedContactSearch, setDebouncedContactSearch] = useState("");
  const [selectedContactId, setSelectedContactId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedContactSearch(contactSearch.trim()),
      250,
    );
    return () => window.clearTimeout(timer);
  }, [contactSearch]);

  const contactParams = {
    page: 1,
    page_size: 20,
    ...(debouncedContactSearch ? { search: debouncedContactSearch } : {}),
  };
  const contactsQuery = useQuery({
    queryKey: queryKeys.contacts.list(workspaceId, contactParams),
    queryFn: () => contactsApi.list(workspaceId, contactParams),
    enabled: true,
    ...STATIC,
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      const trimmedName = name.trim();
      if (!trimmedName) throw new Error("Enter a project name.");
      if (!selectedContactId) throw new Error("Select a customer.");
      if (mode === "recover" && !browserDraft) {
        throw new Error("The browser draft is no longer available.");
      }

      const document =
        mode === "recover" && browserDraft
          ? {
              version: browserDraft.version,
              activeShotId: browserDraft.activeShotId,
              shots: browserDraft.shots,
              updatedAt: browserDraft.updatedAt,
            }
          : undefined;
      const created = await lightingProjectsApi.create(workspaceId, {
        contact_id: selectedContactId,
        name: trimmedName,
        ...(document ? { document } : {}),
      });

      let cleanupFailed = false;
      if (mode === "recover") {
        try {
          await deleteLandscapeDraft(workspaceId);
        } catch {
          cleanupFailed = true;
        }
      }
      return { created, cleanupFailed };
    },
    onSuccess: ({ created, cleanupFailed }) => {
      queryClient.setQueryData(
        queryKeys.lightingProjects.detail(workspaceId, created.id),
        created,
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.lightingProjects.all(workspaceId),
      });
      if (mode === "recover") {
        queryClient.setQueryData(
          queryKeys.lightingProjects.browserDraft(workspaceId),
          null,
        );
      }
      if (cleanupFailed) {
        toast.warning(
          "Project recovered, but this browser could not remove the old draft.",
        );
      } else {
        toast.success(
          mode === "recover" ? "Browser draft recovered" : "Lighting project created",
        );
      }
      router.push(`/landscape-lighting/${created.id}`);
    },
    onError: (error: unknown) => {
      setFormError(getApiErrorMessage(error, "Could not create this project."));
    },
  });

  const contacts = contactsQuery.data?.items ?? [];

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "recover"
              ? "Recover browser draft"
              : "New lighting project"}
          </DialogTitle>
          <DialogDescription>
            {mode === "recover"
              ? "Link the drawing saved in this browser to a customer project in Tribunal. The local draft is removed only after the project is created."
              : "Name the lighting plan and link it to the customer who owns the work."}
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            setFormError(null);
            createMutation.mutate();
          }}
        >
          <div className="space-y-2">
            <label htmlFor={nameId} className="text-sm font-medium">
              Project name
            </label>
            <Input
              id={nameId}
              value={name}
              maxLength={200}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
              placeholder="Lee residence lighting"
              disabled={createMutation.isPending}
              aria-invalid={Boolean(formError && !name.trim())}
            />
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Customer</legend>
            <label htmlFor={searchId} className="sr-only">
              Search customers
            </label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                id={searchId}
                value={contactSearch}
                onChange={(event) => setContactSearch(event.target.value)}
                placeholder="Search customers by name or email"
                className="pl-9"
                disabled={createMutation.isPending}
              />
            </div>
            <div className="max-h-52 overflow-y-auto rounded-md border" role="group">
              {contactsQuery.isPending ? (
                <div className="flex items-center gap-2 px-3 py-4 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  Loading customers...
                </div>
              ) : contactsQuery.isError ? (
                <div className="space-y-2 px-3 py-4 text-sm text-muted-foreground">
                  <p>Customers could not be loaded.</p>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => contactsQuery.refetch()}
                  >
                    Try again
                  </Button>
                </div>
              ) : contacts.length === 0 ? (
                <p className="px-3 py-4 text-sm text-muted-foreground">
                  No matching customers.
                </p>
              ) : (
                contacts.map((contact) => {
                  const label = contactLabel(contact);
                  return (
                    <label
                      key={contact.id}
                      className="flex cursor-pointer items-start gap-3 border-b px-3 py-3 last:border-b-0 hover:bg-muted/60 has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-[-2px] has-[:focus-visible]:outline-ring"
                    >
                      <input
                        type="radio"
                        name="lighting-project-contact"
                        value={contact.id}
                        checked={selectedContactId === contact.id}
                        onChange={() => setSelectedContactId(contact.id)}
                        className="mt-1 accent-primary"
                        disabled={createMutation.isPending}
                      />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">
                          {label}
                        </span>
                        {contact.email ? (
                          <span className="block truncate text-xs text-muted-foreground">
                            {contact.email}
                          </span>
                        ) : null}
                      </span>
                    </label>
                  );
                })
              )}
            </div>
          </fieldset>

          {formError ? (
            <p className="text-sm text-destructive" role="alert">
              {formError}
            </p>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={createMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={createMutation.isPending || !name.trim() || !selectedContactId}
            >
              {createMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : null}
              {mode === "recover" ? "Recover project" : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ProjectStatus({ status }: { status: LightingProjectSummary["status"] }) {
  return (
    <span className="inline-flex min-h-6 items-center rounded-md border px-2 text-xs font-medium capitalize">
      {status}
    </span>
  );
}

function ProjectActions({
  project,
  pending,
  onArchiveToggle,
}: {
  project: LightingProjectSummary;
  pending: boolean;
  onArchiveToggle: (project: LightingProjectSummary) => void;
}) {
  const archived = project.status === "archived";
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => onArchiveToggle(project)}
        disabled={pending}
      >
        {pending ? (
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        ) : archived ? (
          <ArchiveRestore className="size-4" aria-hidden="true" />
        ) : (
          <Archive className="size-4" aria-hidden="true" />
        )}
        {archived ? "Restore" : "Archive"}
      </Button>
      <Button asChild size="sm" variant="outline">
        <Link href={`/landscape-lighting/${project.id}`}>
          Open project
          <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
      </Button>
    </div>
  );
}

function ProjectRows({
  projects,
  pendingProjectId,
  onArchiveToggle,
}: {
  projects: LightingProjectSummary[];
  pendingProjectId: string | null;
  onArchiveToggle: (project: LightingProjectSummary) => void;
}) {
  return (
    <>
      <div className="hidden overflow-hidden rounded-lg border md:block">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Landscape lighting customer projects</caption>
          <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">
                Project
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Customer
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Status
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Last updated
              </th>
              <th scope="col" className="px-4 py-3 text-right font-medium">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {projects.map((project) => (
              <tr key={project.id}>
                <th scope="row" className="px-4 py-4 font-medium">
                  {project.name}
                </th>
                <td className="px-4 py-4">{project.contact_name}</td>
                <td className="px-4 py-4">
                  <ProjectStatus status={project.status} />
                </td>
                <td className="px-4 py-4 text-muted-foreground">
                  <time dateTime={project.updated_at}>
                    {projectTimeFormatter.format(new Date(project.updated_at))}
                  </time>
                  <span className="block text-xs">
                    {project.updater_name ? `by ${project.updater_name}` : "Updater unavailable"}
                  </span>
                </td>
                <td className="px-4 py-4">
                  <ProjectActions
                    project={project}
                    pending={pendingProjectId === project.id}
                    onArchiveToggle={onArchiveToggle}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="space-y-3 md:hidden" aria-label="Landscape lighting projects">
        {projects.map((project) => (
          <li key={project.id} className="space-y-4 rounded-lg border p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate font-medium">{project.name}</h2>
                <p className="truncate text-sm text-muted-foreground">
                  {project.contact_name}
                </p>
              </div>
              <ProjectStatus status={project.status} />
            </div>
            <p className="text-xs text-muted-foreground">
              Updated {projectTimeFormatter.format(new Date(project.updated_at))}
              {project.updater_name ? ` by ${project.updater_name}` : ""}
            </p>
            <ProjectActions
              project={project}
              pending={pendingProjectId === project.id}
              onArchiveToggle={onArchiveToggle}
            />
          </li>
        ))}
      </ul>
    </>
  );
}

export function LightingProjectsPage({ workspaceId }: LightingProjectsPageProps) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ProjectFilter>("active");
  const [pageNumber, setPageNumber] = useState(1);
  const [createMode, setCreateMode] = useState<CreateMode | null>(null);
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);
  const listParams = {
    status: filter,
    page: pageNumber,
    page_size: 50,
  } as const;

  const projectsQuery = useQuery({
    queryKey: queryKeys.lightingProjects.list(workspaceId, listParams),
    queryFn: () => lightingProjectsApi.list(workspaceId, listParams),
    placeholderData: keepPreviousData,
    ...POLL_30S,
  });
  const browserDraftQuery = useQuery({
    queryKey: queryKeys.lightingProjects.browserDraft(workspaceId),
    queryFn: () => loadLandscapeDraft(workspaceId),
    ...STATIC,
  });

  const archiveMutation = useMutation({
    mutationFn: async (project: LightingProjectSummary) => {
      setPendingProjectId(project.id);
      return lightingProjectsApi.update(workspaceId, project.id, {
        expected_version: project.version,
        status: project.status === "archived" ? "active" : "archived",
      });
    },
    onSuccess: (updated: LightingProjectDetail) => {
      queryClient.setQueryData(
        queryKeys.lightingProjects.detail(workspaceId, updated.id),
        updated,
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.lightingProjects.all(workspaceId),
      });
      toast.success(updated.status === "archived" ? "Project archived" : "Project restored");
    },
    onError: (error: unknown) => {
      toast.error(getApiErrorMessage(error, "Could not update this project."));
      void queryClient.invalidateQueries({
        queryKey: queryKeys.lightingProjects.all(workspaceId),
      });
    },
    onSettled: () => setPendingProjectId(null),
  });

  const projects = projectsQuery.data?.items ?? [];
  const browserDraft = browserDraftQuery.data;

  return (
    <main className="h-full min-h-0 overflow-y-auto" aria-labelledby="lighting-projects-heading">
      <div className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-2xl">
            <h1 id="lighting-projects-heading" className="text-2xl font-semibold tracking-tight">
              Landscape lighting projects
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Open a customer plan, design on property photos, and keep the current drawing synced to Tribunal.
            </p>
          </div>
          <Button type="button" onClick={() => setCreateMode("create")}>
            <Plus className="size-4" aria-hidden="true" />
            New lighting project
          </Button>
        </header>

        {browserDraft ? (
          <section className="flex flex-col gap-4 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between" aria-labelledby="browser-draft-heading">
            <div className="flex min-w-0 items-start gap-3">
              <FolderOpen className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div>
                <h2 id="browser-draft-heading" className="font-medium">
                  Browser draft found
                </h2>
                <p className="text-sm text-muted-foreground">
                  Recover the previous workspace drawing into a named customer project before continuing.
                </p>
              </div>
            </div>
            <Button type="button" variant="outline" onClick={() => setCreateMode("recover")}>
              Recover browser draft
            </Button>
          </section>
        ) : null}

        <div className="flex items-center gap-2" role="group" aria-label="Project status filter">
          <Button
            type="button"
            size="sm"
            variant={filter === "active" ? "default" : "outline"}
            aria-pressed={filter === "active"}
            onClick={() => {
              setFilter("active");
              setPageNumber(1);
            }}
          >
            Active
          </Button>
          <Button
            type="button"
            size="sm"
            variant={filter === "archived" ? "default" : "outline"}
            aria-pressed={filter === "archived"}
            onClick={() => {
              setFilter("archived");
              setPageNumber(1);
            }}
          >
            Archived
          </Button>
        </div>

        {projectsQuery.isPending ? (
          <PageLoadingState message="Loading lighting projects..." />
        ) : projectsQuery.isError ? (
          <PageErrorState
            message="Lighting projects could not be loaded."
            onRetry={() => projectsQuery.refetch()}
          />
        ) : projects.length === 0 ? (
          <PageEmptyState
            icon={
              filter === "active" ? (
                <UserRound className="size-9" aria-hidden="true" />
              ) : (
                <Archive className="size-9" aria-hidden="true" />
              )
            }
            title={filter === "active" ? "No active lighting projects" : "No archived lighting projects"}
            description={
              filter === "active"
                ? "Create a customer project to start a server-backed lighting plan."
                : "Archived projects stay recoverable and will appear here."
            }
            action={
              filter === "active" ? (
                <Button type="button" variant="outline" onClick={() => setCreateMode("create")}>
                  <Plus className="size-4" aria-hidden="true" />
                  New lighting project
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <ProjectRows
              projects={projects}
              pendingProjectId={pendingProjectId}
              onArchiveToggle={(project) => archiveMutation.mutate(project)}
            />
            {(projectsQuery.data?.pages ?? 0) > 1 ? (
              <nav
                className="flex items-center justify-end gap-3"
                aria-label="Lighting project pages"
              >
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={pageNumber <= 1 || projectsQuery.isFetching}
                  onClick={() => setPageNumber((page) => Math.max(1, page - 1))}
                >
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground" aria-live="polite">
                  Page {pageNumber} of {projectsQuery.data?.pages ?? 1}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={
                    pageNumber >= (projectsQuery.data?.pages ?? 1) ||
                    projectsQuery.isFetching
                  }
                  onClick={() => setPageNumber((page) => page + 1)}
                >
                  Next
                </Button>
              </nav>
            ) : null}
          </>
        )}
      </div>

      {createMode ? (
        <DraftCreateDialog
          key={createMode}
          workspaceId={workspaceId}
          mode={createMode}
          browserDraft={browserDraft}
          onOpenChange={(open) => {
            if (!open) setCreateMode(null);
          }}
        />
      ) : null}
    </main>
  );
}
