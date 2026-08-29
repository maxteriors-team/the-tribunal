"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Images, Loader2, Trash2 } from "lucide-react";
import Image from "next/image";
import { useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  type HandoffImage,
  deleteQuoteHandoffImage,
  jobHandoffImageUrl,
  listJobHandoffImages,
  listQuoteHandoffImages,
  quoteHandoffImageUrl,
  uploadQuoteHandoffImage,
} from "@/lib/api/handoff-images";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

interface QuoteHandoffImagesProps {
  mode: "quote";
  workspaceId: string;
  quoteId: string;
}

interface JobHandoffImagesProps {
  mode: "job";
  workspaceId: string;
  jobId: string;
}

type HandoffImagesProps = QuoteHandoffImagesProps | JobHandoffImagesProps;

type Notice = { kind: "error" | "success"; text: string };

interface UploadResult {
  uploaded: number;
  failures: Array<{ filename: string; message: string }>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  const megabytes = bytes / (1024 * 1024);
  return `${Number.isInteger(megabytes) ? megabytes : megabytes.toFixed(1)} MB`;
}

export function HandoffImages(props: HandoffImagesProps) {
  const { mode, workspaceId } = props;
  const resourceId = mode === "quote" ? props.quoteId : props.jobId;
  const resourceKey = `${mode}:${resourceId}`;
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const headingId = useId();
  const limitsId = useId();
  const [noticeState, setNoticeState] = useState<{
    resourceKey: string;
    notice: Notice | null;
  }>({ resourceKey, notice: null });
  const notice = noticeState.resourceKey === resourceKey ? noticeState.notice : null;
  const setNotice = (next: Notice | null) => setNoticeState({ resourceKey, notice: next });

  const imageQuery = useQuery({
    queryKey:
      mode === "quote"
        ? queryKeys.quotes.handoffImages(workspaceId, resourceId)
        : queryKeys.jobs.handoffImages(workspaceId, resourceId),
    queryFn: () =>
      mode === "quote"
        ? listQuoteHandoffImages(workspaceId, resourceId)
        : listJobHandoffImages(workspaceId, resourceId),
    staleTime: 60_000,
  });

  const invalidateImageCaches = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.quotes.all(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all(workspaceId) }),
    ]);

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]): Promise<UploadResult> => {
      const result: UploadResult = { uploaded: 0, failures: [] };
      for (const file of files) {
        try {
          await uploadQuoteHandoffImage(workspaceId, resourceId, file);
          result.uploaded += 1;
        } catch (error) {
          result.failures.push({
            filename: file.name,
            message: getApiErrorMessage(error, "Upload failed"),
          });
        }
      }
      return result;
    },
    onSuccess: (result) => {
      void invalidateImageCaches();
      if (result.failures.length > 0) {
        const failureDetails = result.failures
          .map(({ filename, message }) => `${filename}: ${message}`)
          .join("; ");
        setNotice({
          kind: "error",
          text: `${result.uploaded} uploaded. ${result.failures.length} failed — ${failureDetails}`,
        });
        return;
      }
      setNotice({
        kind: "success",
        text: `${result.uploaded} image${result.uploaded === 1 ? "" : "s"} uploaded.`,
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (image: HandoffImage) => deleteQuoteHandoffImage(workspaceId, resourceId, image.id),
    onSuccess: (_data, image) => {
      void invalidateImageCaches();
      setNotice({ kind: "success", text: `${image.filename} removed.` });
    },
    onError: (error, image) => {
      setNotice({
        kind: "error",
        text: getApiErrorMessage(error, `Couldn't remove ${image.filename}`),
      });
    },
  });

  const selectFiles = (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0 || !imageQuery.data) return;
    const files = Array.from(fileList);
    const remaining = imageQuery.data.max_images - imageQuery.data.images.length;
    if (files.length > remaining) {
      setNotice({
        kind: "error",
        text:
          remaining === 0
            ? "The handoff image limit has been reached."
            : `Only ${remaining} image spot${remaining === 1 ? "" : "s"} remaining.`,
      });
      return;
    }

    const invalidType = files.find((file) => !ALLOWED_IMAGE_TYPES.has(file.type));
    if (invalidType) {
      setNotice({
        kind: "error",
        text: `${invalidType.name} must be a JPEG, PNG, or WebP image.`,
      });
      return;
    }
    const emptyFile = files.find((file) => file.size === 0);
    if (emptyFile) {
      setNotice({ kind: "error", text: `${emptyFile.name} is empty.` });
      return;
    }
    const oversized = files.find((file) => file.size > imageQuery.data.max_image_bytes);
    if (oversized) {
      setNotice({
        kind: "error",
        text: `${oversized.name} exceeds the ${formatBytes(imageQuery.data.max_image_bytes)} limit.`,
      });
      return;
    }

    setNotice(null);
    uploadMutation.mutate(files);
  };

  const images = imageQuery.data?.images ?? [];
  const atCapacity = !!imageQuery.data && images.length >= imageQuery.data.max_images;
  const isMutating = uploadMutation.isPending || deleteMutation.isPending;
  const imageUrl = (image: HandoffImage) =>
    mode === "quote"
      ? quoteHandoffImageUrl(workspaceId, resourceId, image.id)
      : jobHandoffImageUrl(workspaceId, resourceId, image.id);

  return (
    <section aria-labelledby={headingId} className="space-y-3 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 id={headingId} className="flex items-center gap-2 text-sm font-medium">
            <Images className="size-4 text-muted-foreground" aria-hidden="true" />
            Field handoff images
          </h3>
          <p className="text-xs text-muted-foreground">
            {mode === "quote"
              ? "Shared with the assigned field team after scheduling."
              : "Photos shared by the office for this job."}
          </p>
          {imageQuery.data ? (
            <p id={limitsId} className="text-xs text-muted-foreground">
              Limit: {imageQuery.data.max_images} images,{" "}
              {formatBytes(imageQuery.data.max_image_bytes)} each. JPEG, PNG, or WebP.
            </p>
          ) : null}
        </div>

        {mode === "quote" ? (
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!imageQuery.data || isMutating || atCapacity}
              aria-describedby={imageQuery.data ? limitsId : undefined}
              onClick={() => fileInputRef.current?.click()}
            >
              {uploadMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <ImagePlus className="size-4" aria-hidden="true" />
              )}
              {uploadMutation.isPending
                ? "Uploading…"
                : atCapacity
                  ? "Limit reached"
                  : "Add images"}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              className="hidden"
              disabled={!imageQuery.data || isMutating || atCapacity}
              onChange={(event) => {
                selectFiles(event.target.files);
                event.target.value = "";
              }}
            />
          </>
        ) : null}
      </div>

      {notice ? (
        <p
          role={notice.kind === "error" ? "alert" : "status"}
          className={notice.kind === "error" ? "text-xs text-destructive" : "text-xs text-success"}
        >
          {notice.text}
        </p>
      ) : null}

      {imageQuery.isPending ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          Loading handoff images…
        </p>
      ) : imageQuery.isError ? (
        <div
          className="flex items-center justify-between gap-3 text-xs text-destructive"
          role="alert"
        >
          <span>Handoff images couldn&apos;t be loaded.</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void imageQuery.refetch()}
          >
            Retry
          </Button>
        </div>
      ) : images.length === 0 ? (
        <p className="rounded-md bg-muted/40 px-3 py-4 text-center text-xs text-muted-foreground">
          {mode === "quote"
            ? "No handoff images added yet."
            : "No handoff images were provided for this job."}
        </p>
      ) : (
        <ul aria-label="Handoff images" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {images.map((image) => (
            <li
              key={image.id}
              className="group relative overflow-hidden rounded-md border bg-muted"
            >
              <a
                href={imageUrl(image)}
                target="_blank"
                rel="noopener noreferrer"
                className="relative block aspect-square focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                title={`Open ${image.filename}`}
              >
                <Image
                  src={imageUrl(image)}
                  alt={image.filename}
                  fill
                  sizes="(min-width: 640px) 33vw, 50vw"
                  unoptimized
                  className="object-cover transition-transform group-hover:scale-105"
                />
              </a>
              {mode === "quote" ? (
                <Button
                  type="button"
                  variant="secondary"
                  size="icon-sm"
                  className="absolute right-1 top-1 shadow-sm"
                  aria-label={`Remove ${image.filename}`}
                  disabled={isMutating}
                  onClick={() => deleteMutation.mutate(image)}
                >
                  <Trash2 className="size-3.5" aria-hidden="true" />
                </Button>
              ) : null}
              <p className="truncate bg-background/90 px-2 py-1 text-xs" title={image.filename}>
                {image.filename}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
