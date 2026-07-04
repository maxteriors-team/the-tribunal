"use client";

import { useQuery } from "@tanstack/react-query";
import { Camera, ExternalLink } from "lucide-react";

import { Separator } from "@/components/ui/separator";
import { getContactCompanyCamPhotos } from "@/lib/api/companycam";
import { queryKeys } from "@/lib/query-keys";
import { useWorkspace } from "@/providers/workspace-provider";

interface ContactPhotosProps {
  contactId: number;
}

/**
 * CompanyCam job-photo gallery for one contact. Renders nothing when the
 * integration isn't connected or no projects match — the section only appears
 * when there is something to show.
 */
export function ContactPhotos({ contactId }: ContactPhotosProps) {
  const { currentWorkspaceId } = useWorkspace();

  const { data } = useQuery({
    queryKey: queryKeys.contacts.companycamPhotos(
      currentWorkspaceId ?? "",
      contactId
    ),
    queryFn: () => getContactCompanyCamPhotos(currentWorkspaceId!, contactId),
    enabled: !!currentWorkspaceId && !!contactId,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  if (!data?.connected || data.projects.length === 0) return null;

  return (
    <>
      <Separator />
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-muted-foreground px-2 flex items-center gap-2">
          <Camera className="h-4 w-4" />
          Job Photos
        </h3>
        {data.projects.map((project) => (
          <div key={project.project_id} className="px-2 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">
                  {project.project_name}
                </p>
                {project.address && (
                  <p className="text-xs text-muted-foreground truncate">
                    {project.address}
                  </p>
                )}
              </div>
              <a
                href={project.project_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 shrink-0"
              >
                {project.photo_count} photo{project.photo_count !== 1 ? "s" : ""}
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
            {project.photos.length > 0 && (
              <div className="grid grid-cols-4 gap-1.5">
                {project.photos.slice(0, 8).map((photo) => (
                  <a
                    key={photo.id}
                    href={photo.web_url || project.project_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block aspect-square overflow-hidden rounded-md bg-muted"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element -- remote CompanyCam CDN thumbnails */}
                    <img
                      src={photo.thumbnail_url}
                      alt={`Job site — ${project.project_name}`}
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform hover:scale-105"
                    />
                  </a>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
