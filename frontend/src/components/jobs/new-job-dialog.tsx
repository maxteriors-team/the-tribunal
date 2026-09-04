"use client";

import { CalendarDays, ImagePlus, Loader2, Plus, RotateCcw, Users, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { TechnicianSelect } from "@/components/jobs/technician-select";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ContactPicker } from "@/components/ui/contact-combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useCreateJob, useWorkspaceTechnicians } from "@/hooks/useJobs";
import {
  HANDOFF_IMAGE_CONTENT_TYPES,
  MAX_HANDOFF_IMAGE_BYTES,
  MAX_HANDOFF_IMAGES,
  uploadJobHandoffImage,
} from "@/lib/api/handoff-images";
import type { JobCreateRequest } from "@/lib/api/jobs";
import { jobWindowError, localToIso } from "@/lib/jobs/job-derivations";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface NewJobDialogProps {
  workspaceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const ALLOWED_IMAGE_TYPES = new Set<string>(HANDOFF_IMAGE_CONTENT_TYPES);

const EMPTY_FORM = {
  contactId: "",
  title: "",
  description: "",
  date: "",
  startTime: "09:00",
  endTime: "17:00",
  scheduleLater: false,
  anytime: false,
};

function localDateTime(date: string, time: string) {
  return date && time ? `${date}T${time}` : "";
}

export function NewJobDialog({ workspaceId, open, onOpenChange }: NewJobDialogProps) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [selectedTechs, setSelectedTechs] = useState<string[]>([]);
  const [stagedImages, setStagedImages] = useState<File[]>([]);
  const [imageError, setImageError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { data: techData } = useWorkspaceTechnicians(workspaceId, open);
  const createJob = useCreateJob(workspaceId);
  const technicians = useMemo(() => techData?.items ?? [], [techData?.items]);

  const start = form.scheduleLater
    ? ""
    : localDateTime(form.date, form.anytime ? "00:00" : form.startTime);
  const end = form.scheduleLater
    ? ""
    : localDateTime(form.date, form.anytime ? "23:59" : form.endTime);
  const windowError = jobWindowError(start, end);
  const hasSchedule = form.scheduleLater || Boolean(form.date);
  const canSubmit =
    Boolean(form.contactId) && form.title.trim().length > 0 && hasSchedule && !windowError;

  const reset = () => {
    setForm(EMPTY_FORM);
    setSelectedTechs([]);
    setStagedImages([]);
    setImageError(null);
  };

  const handleOpenChange = (next: boolean) => {
    if (!next && isSubmitting) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const toggleTech = (id: string) => {
    setSelectedTechs((current) =>
      current.includes(id) ? current.filter((technicianId) => technicianId !== id) : [...current, id],
    );
  };

  const stageImages = (fileList: FileList | null) => {
    if (!fileList?.length) return;
    const files = Array.from(fileList);
    if (stagedImages.length + files.length > MAX_HANDOFF_IMAGES) {
      setImageError(`A job can have at most ${MAX_HANDOFF_IMAGES} handoff images.`);
      return;
    }
    const invalidType = files.find((file) => !ALLOWED_IMAGE_TYPES.has(file.type));
    if (invalidType) {
      setImageError(`${invalidType.name} must be a JPEG, PNG, or WebP image.`);
      return;
    }
    const emptyFile = files.find((file) => file.size === 0);
    if (emptyFile) {
      setImageError(`${emptyFile.name} is empty.`);
      return;
    }
    const oversized = files.find((file) => file.size > MAX_HANDOFF_IMAGE_BYTES);
    if (oversized) {
      setImageError(`${oversized.name} exceeds the 10 MB limit.`);
      return;
    }
    setImageError(null);
    setStagedImages((current) => [...current, ...files]);
  };

  const handleSubmit = async () => {
    if (!canSubmit || isSubmitting) return;
    setIsSubmitting(true);
    const body: JobCreateRequest = {
      contact_id: Number(form.contactId),
      title: form.title.trim(),
      description: form.description.trim() || null,
      scheduled_start: form.scheduleLater ? null : localToIso(start),
      scheduled_end: form.scheduleLater ? null : localToIso(end),
      technician_ids: selectedTechs,
    };
    try {
      const job = await createJob.mutateAsync(body);
      const failures: string[] = [];
      for (const file of stagedImages) {
        try {
          await uploadJobHandoffImage(workspaceId, job.id, file);
        } catch (error) {
          failures.push(`${file.name}: ${getApiErrorMessage(error, "Upload failed")}`);
        }
      }
      if (failures.length > 0) {
        toast.error(
          `Job created, but ${failures.length} of ${stagedImages.length} images failed — ${failures.join("; ")}. Add them from job details.`,
        );
      } else {
        toast.success(
          stagedImages.length === 0
            ? "Job created"
            : `Job created with ${stagedImages.length} handoff image${stagedImages.length === 1 ? "" : "s"}`,
        );
      }
      reset();
      onOpenChange(false);
    } catch {
      toast.error("Failed to create job");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[92vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[760px]">
        <DialogHeader className="border-b px-6 py-5">
          <DialogTitle>New Job</DialogTitle>
          <DialogDescription>Create the work order and its first visit.</DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto px-6 py-5">
          <section aria-labelledby="job-details-heading" className="space-y-4">
            <h3 id="job-details-heading" className="text-sm font-semibold text-foreground">
              Job details
            </h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="job-contact">Customer</Label>
                <ContactPicker
                  id="job-contact"
                  workspaceId={workspaceId}
                  value={form.contactId}
                  onChange={(contactId) => setForm((current) => ({ ...current, contactId }))}
                  placeholder="Search customers by name, phone, or email…"
                />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="job-title">Title</Label>
                <Input
                  id="job-title"
                  placeholder="e.g. Landscape lighting installation"
                  value={form.title}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, title: event.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="job-description">Job notes</Label>
                <Textarea
                  id="job-description"
                  placeholder="Scope, access details, materials, or customer requests…"
                  value={form.description}
                  maxLength={5000}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, description: event.target.value }))
                  }
                  className="min-h-28"
                />
                <p className="text-xs text-muted-foreground">
                  Shared with assigned technicians. {form.description.length}/5000
                </p>
              </div>
              <div className="space-y-2 sm:col-span-2">
                <div className="flex items-center justify-between gap-3">
                  <Label htmlFor="job-handoff-images" className="flex items-center gap-2">
                    <ImagePlus className="size-4" aria-hidden="true" />
                    Field handoff images
                  </Label>
                  <span className="text-xs text-muted-foreground">
                    {stagedImages.length}/{MAX_HANDOFF_IMAGES}
                  </span>
                </div>
                <Input
                  id="job-handoff-images"
                  type="file"
                  accept={HANDOFF_IMAGE_CONTENT_TYPES.join(",")}
                  multiple
                  disabled={isSubmitting || stagedImages.length >= MAX_HANDOFF_IMAGES}
                  onChange={(event) => {
                    stageImages(event.target.files);
                    event.target.value = "";
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  JPEG, PNG, or WebP. Up to 10 MB each.
                </p>
                {imageError ? (
                  <p role="alert" className="text-xs text-destructive">
                    {imageError}
                  </p>
                ) : null}
                {stagedImages.length > 0 ? (
                  <ul aria-label="Selected handoff images" className="space-y-1">
                    {stagedImages.map((file, index) => (
                      <li
                        key={`${file.name}-${file.size}-${index}`}
                        className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
                      >
                        <span className="truncate" title={file.name}>
                          {file.name}
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Remove ${file.name}`}
                          disabled={isSubmitting}
                          onClick={() =>
                            setStagedImages((current) =>
                              current.filter((_candidate, candidateIndex) => candidateIndex !== index),
                            )
                          }
                        >
                          <X className="size-4" aria-hidden="true" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>
          </section>

          <div className="my-6 border-t" />

          <section aria-labelledby="visit-heading" className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 id="visit-heading" className="text-sm font-semibold text-foreground">
                  Visit
                </h3>
                <p className="mt-1 text-sm text-muted-foreground">One-off visit</p>
              </div>
              <CalendarDays className="size-5 text-muted-foreground" aria-hidden="true" />
            </div>

            <div className="flex items-center gap-3 rounded-md border p-3">
              <Checkbox
                id="job-schedule-later"
                checked={form.scheduleLater}
                onCheckedChange={(checked) =>
                  setForm((current) => ({ ...current, scheduleLater: checked === true }))
                }
              />
              <Label htmlFor="job-schedule-later" className="cursor-pointer font-medium">
                Schedule later
              </Label>
            </div>

            <div
              className={cn("grid gap-4 sm:grid-cols-3", form.scheduleLater && "hidden")}
              aria-hidden={form.scheduleLater}
            >
              <div className="space-y-1.5">
                <Label htmlFor="job-date">Date</Label>
                <Input
                  id="job-date"
                  type="date"
                  value={form.date}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, date: event.target.value }))
                  }
                  disabled={form.scheduleLater}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="job-start">Start time</Label>
                <Input
                  id="job-start"
                  type="time"
                  value={form.startTime}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, startTime: event.target.value }))
                  }
                  disabled={form.scheduleLater || form.anytime}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="job-end">End time</Label>
                <Input
                  id="job-end"
                  type="time"
                  value={form.endTime}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, endTime: event.target.value }))
                  }
                  disabled={form.scheduleLater || form.anytime}
                />
              </div>
            </div>

            {!form.scheduleLater && (
              <div className="flex items-center gap-3">
                <Checkbox
                  id="job-anytime"
                  checked={form.anytime}
                  onCheckedChange={(checked) =>
                    setForm((current) => ({ ...current, anytime: checked === true }))
                  }
                />
                <Label htmlFor="job-anytime" className="cursor-pointer font-normal">
                  Anytime
                </Label>
              </div>
            )}
            {windowError && <p className="text-sm text-destructive">{windowError}</p>}

            <div className="space-y-2">
              <Label className="flex items-center gap-2">
                <Users className="size-4" aria-hidden="true" /> Assign technicians
              </Label>
              <TechnicianSelect
                technicians={technicians}
                selectedIds={selectedTechs}
                onToggle={toggleTech}
              />
              <p className="text-xs text-muted-foreground">
                Assigned technicians can see this visit on their calendar.
              </p>
            </div>

          </section>
        </div>

        <DialogFooter className="border-t bg-background px-6 py-4 sm:justify-between">
          <Button type="button" variant="ghost" onClick={reset} disabled={isSubmitting}>
            <RotateCcw className="mr-2 size-4" aria-hidden="true" />
            Reset
          </Button>
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button type="button" variant="outline" disabled={isSubmitting} onClick={() => handleOpenChange(false)}>
              Cancel
            </Button>
            <Button onClick={() => void handleSubmit()} disabled={!canSubmit || isSubmitting}>
              {isSubmitting ? (
                <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
              ) : (
                <Plus className="mr-2 size-4" aria-hidden="true" />
              )}
              {isSubmitting ? "Saving…" : "Save job"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
