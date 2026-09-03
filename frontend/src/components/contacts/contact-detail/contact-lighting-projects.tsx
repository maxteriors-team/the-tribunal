"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lightbulb, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { lightingProjectsApi } from "@/lib/api/lighting-projects";
import { queryKeys } from "@/lib/query-keys";

interface ContactLightingProjectsProps {
  workspaceId: string;
  contactId: number;
  contactName: string;
  canCreate: boolean;
}

export function ContactLightingProjects({
  workspaceId,
  contactId,
  contactName,
  canCreate,
}: ContactLightingProjectsProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const filters = { contact_id: contactId, project_type: "permanent" as const, page_size: 10 };
  const projectsQuery = useQuery({
    queryKey: queryKeys.lightingProjects.list(workspaceId, filters),
    queryFn: () => lightingProjectsApi.list(workspaceId, filters),
  });
  const createProject = useMutation({
    mutationFn: () =>
      lightingProjectsApi.create(workspaceId, {
        contact_id: contactId,
        name: `${contactName} permanent lighting`.slice(0, 160),
        project_type: "permanent",
      }),
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.lightingProjects.all(workspaceId) });
      router.push(`/permanent-lighting/${project.id}`);
    },
    onError: () => toast.error("Could not create the permanent-lighting project"),
  });

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Lightbulb className="size-4" aria-hidden />
          Permanent lighting
        </CardTitle>
        {canCreate ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => createProject.mutate()}
            disabled={createProject.isPending || createProject.isSuccess}
          >
            {createProject.isPending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Plus className="size-4" aria-hidden />
            )}
            New design
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {projectsQuery.isPending ? (
          <p className="text-muted-foreground text-sm">Loading designs…</p>
        ) : projectsQuery.isError ? (
          <div className="space-y-2">
            <p className="text-destructive text-sm">Couldn’t load permanent-lighting designs.</p>
            <Button size="sm" variant="outline" onClick={() => void projectsQuery.refetch()}>
              Try again
            </Button>
          </div>
        ) : projectsQuery.data.items.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No designs yet. Start one here to keep its quote, mockup, and future job together.
          </p>
        ) : (
          <div className="space-y-2">
            {projectsQuery.data.items.map((project) => (
              <Link
                key={project.id}
                href={`/permanent-lighting/${project.id}`}
                className="hover:bg-muted flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors"
              >
                <span className="min-w-0 truncate font-medium">{project.name}</span>
                <span className="text-muted-foreground ml-3 shrink-0 capitalize">
                  {project.status}
                </span>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
