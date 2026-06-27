"use client";

import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { TechnicianSelect } from "@/components/jobs/technician-select";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useContacts } from "@/hooks/useContacts";
import { useCreateJob, useWorkspaceTechnicians } from "@/hooks/useJobs";
import type { JobCreateRequest } from "@/lib/api/jobs";
import { jobWindowError, localToIso } from "@/lib/jobs/job-derivations";

interface NewJobDialogProps {
  workspaceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const EMPTY_FORM = {
  contactId: "",
  title: "",
  description: "",
  start: "",
  end: "",
};

export function NewJobDialog({ workspaceId, open, onOpenChange }: NewJobDialogProps) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [selectedTechs, setSelectedTechs] = useState<string[]>([]);
  const [contactSearch, setContactSearch] = useState("");

  const { data: contactsData, isPending: contactsLoading } = useContacts(workspaceId, {
    page: 1,
    page_size: 50,
    search: contactSearch || undefined,
  });
  const { data: techData } = useWorkspaceTechnicians(workspaceId, open);
  const createJob = useCreateJob(workspaceId);

  const contacts = useMemo(() => contactsData?.items ?? [], [contactsData?.items]);
  const technicians = useMemo(() => techData?.items ?? [], [techData?.items]);

  const reset = () => {
    setForm(EMPTY_FORM);
    setSelectedTechs([]);
    setContactSearch("");
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const toggleTech = (id: string) => {
    setSelectedTechs((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id],
    );
  };

  const windowError = jobWindowError(form.start, form.end);

  const canSubmit = Boolean(form.contactId) && form.title.trim().length > 0 && !windowError;

  const handleSubmit = () => {
    if (!canSubmit) return;
    const body: JobCreateRequest = {
      contact_id: Number(form.contactId),
      title: form.title.trim(),
      description: form.description.trim() || null,
      scheduled_start: localToIso(form.start),
      scheduled_end: localToIso(form.end),
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
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>New Job</DialogTitle>
          <DialogDescription>
            Create a work order, set a time window, and tag the workers who&apos;ll see it on
            their calendar.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Customer */}
          <div className="space-y-1.5">
            <Label htmlFor="job-contact">Customer</Label>
            <Input
              placeholder="Search contacts…"
              value={contactSearch}
              onChange={(event) => setContactSearch(event.target.value)}
              className="mb-2"
            />
            <Select
              value={form.contactId}
              onValueChange={(value) => setForm((prev) => ({ ...prev, contactId: value }))}
            >
              <SelectTrigger id="job-contact">
                <SelectValue placeholder={contactsLoading ? "Loading…" : "Select a customer"} />
              </SelectTrigger>
              <SelectContent>
                {contacts.map((contact) => (
                  <SelectItem key={contact.id} value={String(contact.id)}>
                    {[contact.first_name, contact.last_name].filter(Boolean).join(" ") ||
                      contact.email ||
                      `Contact #${contact.id}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Title */}
          <div className="space-y-1.5">
            <Label htmlFor="job-title">Title</Label>
            <Input
              id="job-title"
              placeholder="e.g. Replace water heater"
              value={form.title}
              onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <Label htmlFor="job-description">Description</Label>
            <Textarea
              id="job-description"
              placeholder="Scope, parts, access notes…"
              value={form.description}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, description: event.target.value }))
              }
            />
          </div>

          {/* Time window */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="job-start">Starts</Label>
              <Input
                id="job-start"
                type="datetime-local"
                value={form.start}
                onChange={(event) => setForm((prev) => ({ ...prev, start: event.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="job-end">Ends</Label>
              <Input
                id="job-end"
                type="datetime-local"
                value={form.end}
                onChange={(event) => setForm((prev) => ({ ...prev, end: event.target.value }))}
              />
            </div>
          </div>
          {windowError && <p className="text-xs text-destructive">{windowError}</p>}

          {/* Tag workers */}
          <div className="space-y-1.5">
            <Label>Assign technicians</Label>
            <TechnicianSelect
              technicians={technicians}
              selectedIds={selectedTechs}
              onToggle={toggleTech}
            />
            <p className="text-xs text-muted-foreground">
              Only technicians linked to a login see jobs on their own calendar.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit || createJob.isPending}>
            {createJob.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Create job
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
