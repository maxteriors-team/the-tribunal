import {
  Download,
  File,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react";
import Image from "next/image";

import { cn } from "@/lib/utils";
import type { TimelineAttachment } from "@/types/conversation";

interface MessageAttachmentsProps {
  attachments: TimelineAttachment[];
}

function attachmentKind(contentType: string): "image" | "video" | "file" {
  if (contentType.startsWith("image/")) return "image";
  if (contentType.startsWith("video/")) return "video";
  return "file";
}

function processingLabel(attachment: TimelineAttachment): string {
  const kind = attachmentKind(attachment.content_type);
  if (kind === "image") return "Receiving photo…";
  if (kind === "video") return "Receiving video…";
  return "Receiving attachment…";
}

function fileSizeLabel(sizeBytes?: number | null): string | null {
  if (sizeBytes == null) return null;
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function MessageAttachments({ attachments }: MessageAttachmentsProps) {
  if (attachments.length === 0) return null;

  return (
    <div className="mb-2 grid gap-2" aria-label="Message attachments">
      {attachments.map((attachment) => {
        const kind = attachmentKind(attachment.content_type);

        if (
          attachment.status === "pending" ||
          attachment.status === "processing"
        ) {
          return (
            <div
              key={attachment.id}
              className="flex min-h-20 min-w-52 items-center gap-3 rounded-lg border border-border/60 bg-background/50 px-4 py-3 text-muted-foreground"
              role="status"
            >
              <LoaderCircle className="size-5 shrink-0 animate-spin" />
              <span className="text-sm">{processingLabel(attachment)}</span>
            </div>
          );
        }

        if (attachment.status === "failed") {
          return (
            <div
              key={attachment.id}
              className="flex min-h-20 min-w-52 items-center gap-3 rounded-lg border border-border/60 bg-background/50 px-4 py-3 text-muted-foreground"
            >
              <TriangleAlert className="size-5 shrink-0" />
              <span className="text-sm">Attachment unavailable</span>
            </div>
          );
        }

        if (kind === "image") {
          return (
            <a
              key={attachment.id}
              href={attachment.content_url}
              target="_blank"
              rel="noreferrer"
              className="group relative block overflow-hidden rounded-lg bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={`Open ${attachment.filename}`}
            >
              <Image
                src={attachment.content_url}
                alt={attachment.filename || "Photo attachment"}
                width={640}
                height={480}
                sizes="(max-width: 640px) 70vw, 360px"
                className="max-h-80 h-auto w-auto max-w-full object-contain transition-transform group-hover:scale-[1.01]"
                unoptimized
              />
              <span className="sr-only">Open photo in a new tab</span>
            </a>
          );
        }

        if (kind === "video") {
          return (
            <div key={attachment.id} className="overflow-hidden rounded-lg bg-black">
              {/* Carrier MMS payloads do not include caption-track files. */}
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                src={attachment.content_url}
                controls
                preload="metadata"
                playsInline
                className="max-h-80 w-full min-w-56"
                aria-label={attachment.filename || "Video attachment"}
              >
                <a href={attachment.content_url} target="_blank" rel="noreferrer">
                  Open video attachment
                </a>
              </video>
            </div>
          );
        }

        const sizeLabel = fileSizeLabel(attachment.size_bytes);
        return (
          <a
            key={attachment.id}
            href={attachment.content_url}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "flex min-w-52 items-center gap-3 rounded-lg border border-border/60",
              "bg-background/50 px-4 py-3 transition-colors hover:bg-background/80",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
          >
            <File className="size-5 shrink-0" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">
                {attachment.filename}
              </span>
              {sizeLabel && (
                <span className="block text-xs text-muted-foreground">
                  {sizeLabel}
                </span>
              )}
            </span>
            <Download className="size-4 shrink-0" />
          </a>
        );
      })}
    </div>
  );
}
