"use client";

import { CalendarDays, Loader2, Plus, RotateCcw, Users } from "lucide-react";
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
import type { JobCreateRequest } from "@/lib/api/jobs";
import { jobWindowError, localToIso } from "@/lib/jobs/job-derivations";
import { cn } from "@/lib/utils";

interface NewJobDialogProps {
  workspaceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

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
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const toggleTech = (id: string) => {
    setSelectedTechs((current) =>
      current.includes(id) ? current.filter((technicianId) => technicianId !== id) : [...current, id],
    );
  };

  const handleSubmit = () => {
    if (!canSubmit) return;
    const body: JobCreateRequest = {
      contact_id: Number(form.contactId),
      title: form.title.trim(),
      description: form.description.trim() || null,
      scheduled_start: form.scheduleLater ? null : localToIso(start),
      scheduled_end: form.scheduleLater ? null : localToIso(end),
      technician_ids: selectedTechs,
    };
    createJob.mutate(body, {
      onSuccess: () => {
        toast.success("Job created");
        handleOpenChange(false);
      },
      onError: () => toast.error("Failed to create job"),
    });
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

            <div className="space-y-1.5">
              <Label htmlFor="job-description">Visit instructions</Label>
              <Textarea
                id="job-description"
                placeholder="Scope, access details, materials, or customer requests…"
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({ ...current, description: event.target.value }))
                }
                className="min-h-28"
              />
            </div>
          </section>
        </div>

        <DialogFooter className="border-t bg-background px-6 py-4 sm:justify-between">
          <Button type="button" variant="ghost" onClick={reset} disabled={createJob.isPending}>
            <RotateCcw className="mr-2 size-4" aria-hidden="true" />
            Reset
          </Button>
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={!canSubmit || createJob.isPending}>
              {createJob.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
              ) : (
                <Plus className="mr-2 size-4" aria-hidden="true" />
              )}
              Save job
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
