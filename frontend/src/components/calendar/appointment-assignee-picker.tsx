"use client";

import { UserRoundPlus, X } from "lucide-react";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkspaceBookableStaff } from "@/hooks/useJobs";

interface AppointmentAssigneePickerProps {
  workspaceId: string;
  value: string | null;
  onValueChange: (staffId: string | null) => void;
  disabled?: boolean;
  id?: string;
}

/**
 * Tags one login-backed booking resource on an appointment.
 *
 * A workspace user can have more than one agent-specific staff row, so this
 * picker deliberately collapses the roster to one option per user. It preserves
 * the currently assigned row when possible and otherwise prefers the shared row.
 */
export function AppointmentAssigneePicker({
  workspaceId,
  value,
  onValueChange,
  disabled = false,
  id = "appointment-assignee",
}: AppointmentAssigneePickerProps) {
  const { data, isPending, isError } = useWorkspaceBookableStaff(
    workspaceId,
    Boolean(workspaceId),
  );
  const roster = useMemo(() => data?.items ?? [], [data?.items]);

  const options = useMemo(() => {
    const byUser = new Map<number, (typeof roster)[number]>();

    for (const staff of roster) {
      if (!staff.is_active || staff.user_id == null) continue;
      const existing = byUser.get(staff.user_id);
      const shouldReplace =
        !existing ||
        staff.id === value ||
        (existing.id !== value && existing.agent_id != null && staff.agent_id == null);
      if (shouldReplace) byUser.set(staff.user_id, staff);
    }

    return [...byUser.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [roster, value]);

  const selected = roster.find((staff) => staff.id === value) ?? null;

  return (
    <div className="space-y-2">
      <div>
        <Label htmlFor={id}>Assigned user</Label>
        <p className="text-xs text-muted-foreground">
          Tag a booking-enabled user to put this event on their calendar.
        </p>
      </div>

      <Select value="" onValueChange={onValueChange} disabled={disabled || isPending}>
        <SelectTrigger id={id}>
          <SelectValue
            placeholder={isPending ? "Loading users..." : "Tag a user (optional)"}
          />
        </SelectTrigger>
        <SelectContent>
          {options.map((staff) => (
            <SelectItem key={staff.id} value={staff.id}>
              <span className="flex items-center gap-2">
                <UserRoundPlus className="h-3.5 w-3.5" />
                <span>{staff.name}</span>
                {staff.email ? (
                  <span className="text-xs text-muted-foreground">{staff.email}</span>
                ) : null}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {selected ? (
        <Badge variant="secondary" className="gap-1.5 py-1">
          <UserRoundPlus className="h-3 w-3" />
          {selected.name}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="-mr-1 h-5 w-5 rounded-full"
            onClick={() => onValueChange(null)}
            disabled={disabled}
            aria-label={`Unassign ${selected.name}`}
          >
            <X className="h-3 w-3" />
          </Button>
        </Badge>
      ) : null}

      {!isPending && !isError && options.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No booking-enabled users. An admin can enable calendars in Settings → Team.
        </p>
      ) : null}
      {isError ? (
        <p className="text-xs text-destructive">Could not load assignable users.</p>
      ) : null}
    </div>
  );
}
