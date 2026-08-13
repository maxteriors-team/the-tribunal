import { Users } from "lucide-react";
import Link from "next/link";
import { type Control } from "react-hook-form";

import type { EditAgentFormValues } from "@/components/agents/agent-edit-schema";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface StaffRoutingSectionProps {
  control: Control<EditAgentFormValues>;
  workspaceId: string;
  agentId: string;
}

export function StaffRoutingSection({ control }: StaffRoutingSectionProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Users className="size-4" aria-hidden="true" />
          Sales Team Calendar Routing
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
                    Single rep — use the first available team member
                  </SelectItem>
                  <SelectItem value="round_robin">
                    Round-robin — distribute evenly across the sales team
                  </SelectItem>
                  <SelectItem value="skill_based">
                    Skill-based — match the requested skill, then round-robin
                  </SelectItem>
                </SelectContent>
              </Select>
              <FormDescription>
                The AI checks the selected rep&apos;s own Google Calendar before it offers a time,
                then creates the confirmed appointment there and on the CRM calendar.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <div className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
          Enable reps as bookable in the{" "}
          <Link
            href="/settings?tab=team"
            className="font-medium text-foreground underline underline-offset-4"
          >
            Team settings
          </Link>
          . Each rep connects their own Google account from Integrations; managers and dispatchers
          can view the entire team on the CRM calendar.
        </div>
      </CardContent>
    </Card>
  );
}
