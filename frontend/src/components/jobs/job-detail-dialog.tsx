"use client";

import { CalendarClock, Loader2, Trash2, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { JobCostingPanel } from "@/components/jobs/job-costing-panel";
import { TechnicianSelect } from "@/components/jobs/technician-select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useAssignTechnicians,
  useDeleteJob,
  useScheduleJob,
  useUnassignTechnician,
  useUpdateJob,
  useWorkspaceTechnicians,
} from "@/hooks/useJobs";
import type { Job, JobStatus } from "@/lib/api/jobs";
import {
  JOB_STATUS_VALUES,
  isoToLocalInput,
  jobStatusColors,
  jobStatusLabel,
  jobWindowError,
  localToIso,
  technicianInitials,
} from "@/lib/jobs/job-derivations";
import { formatDate } from "@/lib/utils/date";

interface JobDetailDialogProps {
  workspaceId: string;
  job: Job | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Read-only view for workers looking at their own calendar (no dispatch edits). */
  readOnly?: boolean;
}

/**
 * Job detail + dispatch controls. The parent remounts this per job via a `key`,
 * so editor state initializes straight from the selected job — no effect-based
 * prop syncing needed.
 */
export function JobDetailDialog({
  workspaceId,
  job,
  open,
  onOpenChange,
  readOnly = false,
}: JobDetailDialogProps) {
  const [start, setStart] = useState(() => isoToLocalInput(job?.scheduled_start ?? null));
  const [end, setEnd] = useState(() => isoToLocalInput(job?.scheduled_end ?? null));
  const [selectedTechs, setSelectedTechs] = useState<string[]>(() =>
    (job?.technicians ?? []).map((tech) => tech.id),
  );
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data: techData } = useWorkspaceTechnicians(workspaceId, open && !readOnly);
  const technicians = useMemo(() => techData?.items ?? [], [techData?.items]);

  const scheduleJob = useScheduleJob(workspaceId);
  const updateJob = useUpdateJob(workspaceId);
  const assignTechs = useAssignTechnicians(workspaceId);
  const unassignTech = useUnassignTechnician(workspaceId);
  const deleteJob = useDeleteJob(workspaceId);

  const assignedIds = useMemo(
    () => new Set((job?.technicians ?? []).map((tech) => tech.id)),
    [job],
  );

  const techDirty = useMemo(() => {
    if (selectedTechs.length !== assignedIds.size) return true;
    return selectedTechs.some((id) => !assignedIds.has(id));
  }, [selectedTechs, assignedIds]);

  if (!job) return null;

  const windowError = jobWindowError(start, end);
  const busy =
    scheduleJob.isPending ||
    updateJob.isPending ||
    assignTechs.isPending ||
    unassignTech.isPending ||
    deleteJob.isPending;

  const toggleTech = (id: string) =>
    setSelectedTechs((prev) =>
      prev.includes(id) ? prev.filter((techId) => techId !== id) : [...prev, id],
    );

  const handleSchedule = () => {
    const startIso = localToIso(start);
    const endIso = localToIso(end);
    if (windowError || !startIso || !endIso) return;
    scheduleJob.mutate(
      { jobId: job.id, body: { scheduled_start: startIso, scheduled_end: endIso } },
      {
        onSuccess: () => toast.success("Job scheduled"),
        onError: () => toast.error("Failed to schedule job"),
      },
    );
  };

  const handleStatus = (status: JobStatus) => {
    if (status === job.status) return;
    updateJob.mutate(
      { jobId: job.id, body: { status } },
      {
        onSuccess: () => toast.success("Status updated"),
        onError: () => toast.error("Failed to update status"),
      },
    );
  };

  const handleSaveTechnicians = async () => {
    const selected = new Set(selectedTechs);
    const toAdd = selectedTechs.filter((id) => !assignedIds.has(id));
    const toRemove = [...assignedIds].filter((id) => !selected.has(id));
    if (toAdd.length === 0 && toRemove.length === 0) return;

    try {
      if (toAdd.length > 0) {
        await assignTechs.mutateAsync({ jobId: job.id, body: { technician_ids: toAdd } });
      }
      await Promise.all(
        toRemove.map((technicianId) => unassignTech.mutateAsync({ jobId: job.id, technicianId })),
      );
      toast.success("Assignments updated");
    } catch {
      toast.error("Failed to update assignments");
    }
  };

  const handleDelete = () => {
    deleteJob.mutate(job.id, {
      onSuccess: () => {
        toast.success("Job deleted");
        setConfirmDelete(false);
        onOpenChange(false);
      },
      onError: () => toast.error("Failed to delete job"),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {job.title}
            <Badge variant="outline" className={jobStatusColors[job.status]}>
              {jobStatusLabel(job.status)}
            </Badge>
          </DialogTitle>
          <DialogDescription>
            Customer #{job.contact_id}
            {job.scheduled_start &&
              ` · ${formatDate(job.scheduled_start, { pattern: "EEE, MMM d 'at' h:mm a" })}`}
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="details" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="details">{readOnly ? "Details" : "Dispatch"}</TabsTrigger>
            <TabsTrigger value="field-work">Field work</TabsTrigger>
          </TabsList>
          <TabsContent value="details" className="space-y-5 pt-2">
          {job.description && (
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{job.description}</p>
          )}

          {readOnly ? (
            <div className="space-y-1.5">
              <Label className="flex items-center gap-2">
                <Users className="size-4" />
                Assigned
              </Label>
              {(job.technicians ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No technicians assigned.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {(job.technicians ?? []).map((tech) => (
                    <div
                      key={tech.id}
                      className="flex items-center gap-1.5 rounded-full border py-0.5 pl-0.5 pr-2"
                    >
                      <Avatar className="size-5">
                        <AvatarFallback
                          className="text-[9px] text-white"
                          style={{ backgroundColor: tech.color }}
                        >
                          {technicianInitials(tech.name)}
                        </AvatarFallback>
                      </Avatar>
                      <span className="text-xs">{tech.name}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <>
              {/* Schedule */}
              <div className="space-y-1.5">
                <Label className="flex items-center gap-2">
                  <CalendarClock className="size-4" />
                  Time window
                </Label>
                <div className="grid grid-cols-2 gap-3">
                  <Input
                    aria-label="Start"
                    type="datetime-local"
                    value={start}
                    onChange={(event) => setStart(event.target.value)}
                  />
                  <Input
                    aria-label="End"
                    type="datetime-local"
                    value={end}
                    onChange={(event) => setEnd(event.target.value)}
                  />
                </div>
                {windowError && <p className="text-xs text-destructive">{windowError}</p>}
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handleSchedule}
                  disabled={busy || !start || !end || Boolean(windowError)}
                >
                  {scheduleJob.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
                  Save schedule
                </Button>
              </div>

              {/* Status */}
              <div className="space-y-1.5">
                <Label htmlFor="job-status">Status</Label>
                <Select value={job.status} onValueChange={(value) => handleStatus(value as JobStatus)}>
                  <SelectTrigger id="job-status" disabled={busy}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {JOB_STATUS_VALUES.map((status) => (
                      <SelectItem key={status} value={status}>
                        {jobStatusLabel(status)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Technicians */}
              <div className="space-y-1.5">
                <Label className="flex items-center gap-2">
                  <Users className="size-4" />
                  Assigned technicians
                </Label>
                <TechnicianSelect
                  technicians={technicians}
                  selectedIds={selectedTechs}
                  onToggle={toggleTech}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void handleSaveTechnicians()}
                  disabled={busy || !techDirty}
                >
                  {(assignTechs.isPending || unassignTech.isPending) && (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  )}
                  Save assignments
                </Button>
              </div>

              {/* Delete */}
              <div className="flex justify-end border-t pt-3">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setConfirmDelete(true)}
                  disabled={busy}
                >
                  <Trash2 className="mr-2 size-4" />
                  Delete job
                </Button>
              </div>
            </>
          )}
          </TabsContent>
          <TabsContent value="field-work" className="pt-2">
            <JobCostingPanel workspaceId={workspaceId} jobId={job.id} />
          </TabsContent>
        </Tabs>
      </DialogContent>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete job</AlertDialogTitle>
            <AlertDialogDescription>
              Delete &quot;{job.title}&quot;? This removes it from every assigned worker&apos;s
              calendar and cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleDelete}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  );
}
