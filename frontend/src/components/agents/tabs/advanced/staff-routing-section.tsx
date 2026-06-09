import { Loader2, Plus, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { type Control, useWatch } from "react-hook-form";

import type { EditAgentFormValues } from "@/components/agents/agent-edit-schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  useBookableStaff,
  useCreateBookableStaff,
  useDeleteBookableStaff,
  useUpdateBookableStaff,
} from "@/hooks/useBookableStaff";

interface StaffRoutingSectionProps {
  control: Control<EditAgentFormValues>;
  workspaceId: string;
  agentId: string;
}

const parseSkills = (raw: string): string[] =>
  raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

export function StaffRoutingSection({ control, workspaceId, agentId }: StaffRoutingSectionProps) {
  const strategy = useWatch({ control, name: "assignmentStrategy" });
  const poolEnabled = strategy === "round_robin" || strategy === "skill_based";

  const { data, isLoading } = useBookableStaff(workspaceId, agentId, poolEnabled);
  const createStaff = useCreateBookableStaff(workspaceId, agentId);
  const updateStaff = useUpdateBookableStaff(workspaceId, agentId);
  const deleteStaff = useDeleteBookableStaff(workspaceId, agentId);

  const [newName, setNewName] = useState("");
  const [newEventType, setNewEventType] = useState("");
  const [newSkills, setNewSkills] = useState("");

  const staff = data?.items ?? [];

  const handleAdd = () => {
    const name = newName.trim();
    if (!name) return;
    createStaff.mutate(
      {
        name,
        calcom_event_type_id: newEventType ? Number(newEventType) : null,
        skills: parseSkills(newSkills),
        is_active: true,
      },
      {
        onSuccess: () => {
          setNewName("");
          setNewEventType("");
          setNewSkills("");
        },
      },
    );
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Users className="h-4 w-4" />
          Staff &amp; Skill Routing
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <FormField
          control={control}
          name="assignmentStrategy"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Assignment Strategy</FormLabel>
              <Select onValueChange={field.onChange} value={field.value}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue placeholder="Select strategy" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectItem value="single">
                    Single calendar — always book the agent&apos;s event type
                  </SelectItem>
                  <SelectItem value="round_robin">
                    Round-robin — distribute evenly across the staff pool
                  </SelectItem>
                  <SelectItem value="skill_based">
                    Skill-based — match the requested skill, then round-robin
                  </SelectItem>
                </SelectContent>
              </Select>
              <FormDescription>
                How the AI picks which calendar to book. Round-robin and skill-based strategies
                route bookings to the staff pool below; each staff member books against their own
                Cal.com event type.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        {poolEnabled && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">Bookable Staff Pool</p>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            </div>

            {staff.length === 0 && !isLoading && (
              <p className="text-sm text-muted-foreground">
                No staff yet. Add at least one staff member with a Cal.com event type so the AI has
                somewhere to book.
              </p>
            )}

            <div className="space-y-2">
              {staff.map((member) => (
                <div
                  key={member.id}
                  className="flex flex-wrap items-center gap-2 rounded-md border p-3"
                >
                  <div className="flex-1 min-w-[140px]">
                    <p className="text-sm font-medium">{member.name}</p>
                    <p className="text-xs text-muted-foreground">
                      Event type: {member.calcom_event_type_id ?? "—"} · {member.assignment_count}{" "}
                      booked
                    </p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {member.skills.map((skill) => (
                        <Badge key={skill} variant="secondary" className="text-xs">
                          {skill}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={member.is_active}
                      onCheckedChange={(checked) =>
                        updateStaff.mutate({
                          staffId: member.id,
                          body: { is_active: checked },
                        })
                      }
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => deleteStaff.mutate(member.id)}
                      aria-label={`Remove ${member.name}`}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>

            <div className="rounded-md border border-dashed p-3 space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Add staff member
              </p>
              <div className="grid gap-2 sm:grid-cols-3">
                <Input
                  placeholder="Name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <Input
                  type="number"
                  placeholder="Cal.com event type ID"
                  value={newEventType}
                  onChange={(e) => setNewEventType(e.target.value)}
                />
                <Input
                  placeholder="Skills (comma separated)"
                  value={newSkills}
                  onChange={(e) => setNewSkills(e.target.value)}
                />
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handleAdd}
                disabled={!newName.trim() || createStaff.isPending}
              >
                {createStaff.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                Add staff
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
