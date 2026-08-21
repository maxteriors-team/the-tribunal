"use client";

import { Loader2 } from "lucide-react";
import { FormEvent, useState } from "react";

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
import { Textarea } from "@/components/ui/textarea";
import { TeamMemberPicker } from "@/components/workspaces/team-member-picker";
import type {
  AttendanceAdminCreateRequest,
  AttendanceEntry,
  AttendanceUpdateRequest,
} from "@/lib/api/attendance";

type AttendanceManualEntry = Omit<AttendanceAdminCreateRequest, "request_id">;
type AttendanceCorrection = Omit<AttendanceUpdateRequest, "request_id">;

function toLocalInputValue(value: string): string {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 19);
}

interface AttendanceEntryEditDialogProps {
  entry: AttendanceEntry | null;
  open: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (entryId: string, update: AttendanceCorrection) => void;
}

export function AttendanceEntryEditDialog({
  entry,
  open,
  pending,
  onOpenChange,
  onSave,
}: AttendanceEntryEditDialogProps) {
  const originalStartedAt = entry ? toLocalInputValue(entry.started_at) : "";
  const originalEndedAt = entry?.ended_at ? toLocalInputValue(entry.ended_at) : "";
  const originalNote = entry?.note?.trim() || null;
  const [startedAt, setStartedAt] = useState(originalStartedAt);
  const [endedAt, setEndedAt] = useState(originalEndedAt);
  const [note, setNote] = useState(() => entry?.note ?? "");
  const [reason, setReason] = useState("");
  const normalizedNote = note.trim() || null;
  const hasChanges =
    startedAt !== originalStartedAt ||
    endedAt !== originalEndedAt ||
    normalizedNote !== originalNote;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!entry || !startedAt || !endedAt || !hasChanges || reason.trim().length < 3) return;
    const update: AttendanceCorrection = { reason: reason.trim() };
    if (startedAt !== originalStartedAt) update.started_at = new Date(startedAt).toISOString();
    if (endedAt !== originalEndedAt) update.ended_at = new Date(endedAt).toISOString();
    if (normalizedNote !== originalNote) update.note = normalizedNote;
    onSave(entry.id, update);
  };

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !pending && onOpenChange(nextOpen)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Correct time entry</DialogTitle>
          <DialogDescription>
            Changes are logged with your name and reason. Times below use your device timezone.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="attendance-started-at">Clock in</Label>
              <Input
                id="attendance-started-at"
                type="datetime-local"
                step={1}
                value={startedAt}
                onChange={(event) => setStartedAt(event.target.value)}
                required
                disabled={pending}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="attendance-ended-at">Clock out</Label>
              <Input
                id="attendance-ended-at"
                type="datetime-local"
                step={1}
                value={endedAt}
                onChange={(event) => setEndedAt(event.target.value)}
                required
                disabled={pending}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="attendance-note">Entry note</Label>
            <Textarea
              id="attendance-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={500}
              disabled={pending}
              placeholder="Optional context for payroll review"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="attendance-correction-reason">Correction reason</Label>
            <Textarea
              id="attendance-correction-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              minLength={3}
              maxLength={500}
              required
              disabled={pending}
              aria-describedby="attendance-correction-help"
              placeholder="Why is this record changing?"
            />
            <p id="attendance-correction-help" className="text-xs text-muted-foreground">
              This reason becomes part of the permanent audit history.
            </p>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={pending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                pending ||
                !startedAt ||
                !endedAt ||
                !hasChanges ||
                reason.trim().length < 3
              }
            >
              {pending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
              Save correction
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface AttendanceManualEntryDialogProps {
  workspaceId: string;
  open: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (entry: AttendanceManualEntry) => void;
}

export function AttendanceManualEntryDialog({
  workspaceId,
  open,
  pending,
  onOpenChange,
  onCreate,
}: AttendanceManualEntryDialogProps) {
  const [userId, setUserId] = useState<number | null>(null);
  const [initialTimes] = useState(() => {
    const end = new Date();
    return {
      startedAt: toLocalInputValue(new Date(end.getTime() - 8 * 60 * 60 * 1000).toISOString()),
      endedAt: toLocalInputValue(end.toISOString()),
    };
  });
  const [startedAt, setStartedAt] = useState(initialTimes.startedAt);
  const [endedAt, setEndedAt] = useState(initialTimes.endedAt);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (userId === null || !startedAt || !endedAt || reason.trim().length < 3) return;
    onCreate({
      user_id: userId,
      started_at: new Date(startedAt).toISOString(),
      ended_at: new Date(endedAt).toISOString(),
      note: note.trim() || undefined,
      reason: reason.trim(),
    });
  };

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !pending && onOpenChange(nextOpen)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add recorded hours</DialogTitle>
          <DialogDescription>
            Use this for a missed clock entry. The employee, times, creator, and reason are audited.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <TeamMemberPicker
            workspaceId={workspaceId}
            value={userId}
            onValueChange={setUserId}
            label="Employee"
            triggerId="attendance-manual-employee"
            allowUnassigned={false}
            disabled={pending}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="attendance-manual-start">Clock in</Label>
              <Input
                id="attendance-manual-start"
                type="datetime-local"
                step={1}
                value={startedAt}
                onChange={(event) => setStartedAt(event.target.value)}
                required
                disabled={pending}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="attendance-manual-end">Clock out</Label>
              <Input
                id="attendance-manual-end"
                type="datetime-local"
                step={1}
                value={endedAt}
                onChange={(event) => setEndedAt(event.target.value)}
                required
                disabled={pending}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="attendance-manual-note">Entry note</Label>
            <Textarea
              id="attendance-manual-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={500}
              disabled={pending}
              placeholder="Optional payroll context"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="attendance-manual-reason">Reason</Label>
            <Textarea
              id="attendance-manual-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              minLength={3}
              maxLength={500}
              required
              disabled={pending}
              placeholder="Why is this entry being added manually?"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={pending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                pending || userId === null || !startedAt || !endedAt || reason.trim().length < 3
              }
            >
              {pending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
              Add entry
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface AttendanceEntryVoidDialogProps {
  entry: AttendanceEntry | null;
  open: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (entryId: string, reason: string) => void;
}

export function AttendanceEntryVoidDialog({
  entry,
  open,
  pending,
  onOpenChange,
  onConfirm,
}: AttendanceEntryVoidDialogProps) {
  const [reason, setReason] = useState("");

  return (
    <AlertDialog open={open} onOpenChange={(nextOpen) => !pending && onOpenChange(nextOpen)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Void this time entry?</AlertDialogTitle>
          <AlertDialogDescription>
            The record remains in the audit history but is excluded from totals and payroll exports.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <Label htmlFor="attendance-void-reason">Reason</Label>
          <Textarea
            id="attendance-void-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            minLength={3}
            maxLength={500}
            required
            disabled={pending}
            placeholder="Why should payroll ignore this record?"
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Keep entry</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending || reason.trim().length < 3 || !entry}
            onClick={(event) => {
              event.preventDefault();
              if (entry && reason.trim().length >= 3) onConfirm(entry.id, reason.trim());
            }}
          >
            {pending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
            Void entry
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
