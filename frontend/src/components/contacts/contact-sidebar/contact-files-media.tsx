"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Camera,
  ExternalLink,
  FileIcon,
  Loader2,
  Paperclip,
  Upload,
  X,
} from "lucide-react";
import { useRef } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { getContactCompanyCamPhotos } from "@/lib/api/companycam";
import {
  type ContactAttachment,
  contactAttachmentDownloadUrl,
  deleteContactAttachment,
  listContactAttachments,
  uploadContactAttachment,
} from "@/lib/api/contact-attachments";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useWorkspace } from "@/providers/workspace-provider";

const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface ContactFilesMediaProps {
  contactId: number;
}

/**
 * Files & Media section for one contact: user-uploaded attachments (stored in
 * the CRM) plus job photos matched from CompanyCam. The upload affordance is
 * always visible; the CompanyCam block appears only when the integration is
 * connected and projects match this contact.
 */
export function ContactFilesMedia({ contactId }: ContactFilesMediaProps) {
  const { currentWorkspaceId } = useWorkspace();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const enabled = !!currentWorkspaceId && !!contactId;

  const { data: attachmentData } = useQuery({
    queryKey: queryKeys.contacts.attachments(currentWorkspaceId ?? "", contactId),
    queryFn: () => listContactAttachments(currentWorkspaceId!, contactId),
    enabled,
    staleTime: 60 * 1000,
  });

  const { data: companycam } = useQuery({
    queryKey: queryKeys.contacts.companycamPhotos(
      currentWorkspaceId ?? "",
      contactId
    ),
    queryFn: () => getContactCompanyCamPhotos(currentWorkspaceId!, contactId),
    enabled,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const invalidateAttachments = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.contacts.attachments(currentWorkspaceId ?? "", contactId),
    });

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        await uploadContactAttachment(currentWorkspaceId!, contactId, file);
      }
      return files.length;
    },
    onSuccess: (count) => {
      void invalidateAttachments();
      toast.success(count === 1 ? "File uploaded" : `${count} files uploaded`);
    },
    onError: (error) => {
      void invalidateAttachments();
      toast.error(getApiErrorMessage(error, "Failed to upload file"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (attachmentId: string) =>
      deleteContactAttachment(currentWorkspaceId!, contactId, attachmentId),
    onSuccess: () => {
      void invalidateAttachments();
      toast.success("File deleted");
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Failed to delete file"));
    },
  });

  const handleFilesSelected = (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    const files = Array.from(fileList);
    const oversized = files.find((f) => f.size > MAX_UPLOAD_BYTES);
    if (oversized) {
      toast.error(`"${oversized.name}" is over the 15 MB limit`);
      return;
    }
    uploadMutation.mutate(files);
  };

  const attachments = attachmentData?.attachments ?? [];
  const images = attachments.filter((a) => a.content_type.startsWith("image/"));
  const otherFiles = attachments.filter(
    (a) => !a.content_type.startsWith("image/")
  );
  const companycamProjects =
    companycam?.connected && companycam.projects.length > 0
      ? companycam.projects
      : [];

  const downloadUrl = (attachment: ContactAttachment) =>
    contactAttachmentDownloadUrl(currentWorkspaceId ?? "", contactId, attachment.id);

  return (
    <>
      <Separator />
      <div className="space-y-3">
        <div className="flex items-center justify-between px-2">
          <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <Paperclip className="h-4 w-4" />
            Files & Media
          </h3>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={uploadMutation.isPending}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploadMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Upload className="h-3.5 w-3.5" />
            )}
            Upload
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              handleFilesSelected(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {attachments.length === 0 && companycamProjects.length === 0 && (
          <p className="px-2 text-xs text-muted-foreground">
            No files yet — upload photos, PDFs, or documents for this contact.
          </p>
        )}

        {images.length > 0 && (
          <div className="px-2 grid grid-cols-4 gap-1.5">
            {images.map((attachment) => (
              <div key={attachment.id} className="group relative">
                <a
                  href={downloadUrl(attachment)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block aspect-square overflow-hidden rounded-md bg-muted"
                  title={attachment.filename}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- authenticated same-origin download URL */}
                  <img
                    src={downloadUrl(attachment)}
                    alt={attachment.filename}
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform group-hover:scale-105"
                  />
                </a>
                <button
                  type="button"
                  aria-label={`Delete ${attachment.filename}`}
                  className="absolute -top-1.5 -right-1.5 hidden group-hover:flex items-center justify-center size-5 rounded-full bg-background border shadow-sm text-muted-foreground hover:text-destructive"
                  onClick={() => deleteMutation.mutate(attachment.id)}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {otherFiles.length > 0 && (
          <div className="px-2 space-y-1">
            {otherFiles.map((attachment) => (
              <div
                key={attachment.id}
                className="group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60"
              >
                <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                <a
                  href={downloadUrl(attachment)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 flex-1 text-sm truncate hover:underline"
                  title={attachment.filename}
                >
                  {attachment.filename}
                </a>
                <span className="text-xs text-muted-foreground shrink-0">
                  {formatBytes(attachment.size_bytes)}
                </span>
                <button
                  type="button"
                  aria-label={`Delete ${attachment.filename}`}
                  className="hidden group-hover:block text-muted-foreground hover:text-destructive"
                  onClick={() => deleteMutation.mutate(attachment.id)}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {companycamProjects.length > 0 && (
          <div className="space-y-2">
            <p className="px-2 text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <Camera className="h-3.5 w-3.5" />
              CompanyCam
            </p>
            {companycamProjects.map((project) => (
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
                    {project.photo_count} photo
                    {project.photo_count !== 1 ? "s" : ""}
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
        )}
      </div>
    </>
  );
}
