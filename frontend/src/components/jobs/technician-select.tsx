"use client";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { technicianInitials } from "@/lib/jobs/job-derivations";

/** Minimal technician shape needed to render a tag row. */
export interface TechnicianOption {
  id: string;
  name: string;
  color: string;
  user_id?: number | null;
}

interface TechnicianSelectProps {
  technicians: TechnicianOption[];
  selectedIds: string[];
  onToggle: (id: string) => void;
}

/**
 * Checklist of workspace technicians for tagging onto a job. Shared by the
 * create and detail dialogs so the avatar/login-hint row lives in one place.
 * Technicians without a linked login are flagged because they can't see jobs on
 * their own calendar.
 */
export function TechnicianSelect({ technicians, selectedIds, onToggle }: TechnicianSelectProps) {
  if (technicians.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No technicians in this workspace yet.</p>
    );
  }

  return (
    <ScrollArea className="h-32 rounded-md border p-2">
      <div className="space-y-1">
        {technicians.map((tech) => (
          <label
            key={tech.id}
            htmlFor={`tech-${tech.id}`}
            className="flex items-center gap-2 rounded-md p-1.5 hover:bg-muted/50 cursor-pointer"
          >
            <Checkbox
              id={`tech-${tech.id}`}
              checked={selectedIds.includes(tech.id)}
              onCheckedChange={() => onToggle(tech.id)}
            />
            <Avatar className="size-6">
              <AvatarFallback
                className="text-[10px] text-white"
                style={{ backgroundColor: tech.color }}
              >
                {technicianInitials(tech.name)}
              </AvatarFallback>
            </Avatar>
            <span className="text-sm">{tech.name}</span>
            {!tech.user_id && (
              <span className="ml-auto text-[10px] text-muted-foreground">no login</span>
            )}
          </label>
        ))}
      </div>
    </ScrollArea>
  );
}
