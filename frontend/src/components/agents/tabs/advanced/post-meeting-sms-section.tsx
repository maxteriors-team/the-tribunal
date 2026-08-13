import { type Control, useWatch } from "react-hook-form";

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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

interface PostMeetingSmsSectionProps {
  control: Control<EditAgentFormValues>;
}

export function PostMeetingSmsSection({ control }: PostMeetingSmsSectionProps) {
  const postMeetingEnabled = useWatch({ control, name: "postMeetingSmsEnabled" });
  const postMeetingTemplate = useWatch({ control, name: "postMeetingTemplate" }) ?? "";
  const postMeetingCharCount = postMeetingTemplate.length;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">Post-Meeting SMS</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <FormField
          control={control}
          name="postMeetingSmsEnabled"
          render={({ field }) => (
            <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <FormLabel className="text-base">Enable Post-Meeting SMS</FormLabel>
                <FormDescription>
                  Send a follow-up SMS after the meeting is marked complete on the CRM calendar
                </FormDescription>
              </div>
              <FormControl>
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              </FormControl>
            </FormItem>
          )}
        />

        {postMeetingEnabled && (
          <FormField
            control={control}
            name="postMeetingTemplate"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel>Post-Meeting Message</FormLabel>
                  <span
                    className={`text-xs ${postMeetingCharCount > 160 ? "text-amber-600 font-medium" : "text-muted-foreground"}`}
                  >
                    {postMeetingCharCount} / 160
                    {postMeetingCharCount > 160
                      ? ` (${Math.ceil(postMeetingCharCount / 153)} segments)`
                      : ""}
                  </span>
                </div>
                <FormControl>
                  <Textarea
                    placeholder="Hi {first_name}, great meeting with you today! Here's what we discussed: [key points]. Ready to move forward? Reply here."
                    className="min-h-[90px] font-mono text-sm resize-none"
                    value={field.value ?? ""}
                    onChange={(e) => field.onChange(e.target.value || null)}
                  />
                </FormControl>
                <FormDescription>
                  Sent after the meeting ends. Leave blank to use the default message. Supports{" "}
                  <code className="text-xs font-mono bg-muted rounded px-1">{"{first_name}"}</code>.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
      </CardContent>
    </Card>
  );
}
