import { type Control, useWatch } from "react-hook-form";

import type { EditAgentFormValues } from "@/components/agents/agent-edit-schema";
import { ReminderOffsetsInput } from "@/components/agents/reminder-offsets-input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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

interface RemindersSectionProps {
  control: Control<EditAgentFormValues>;
}

const DEFAULT_REMINDER_TEMPLATE_PLACEHOLDER =
  "Hi {first_name}, this is a reminder about your appointment on {appointment_date} at {appointment_time}. Reply STOP to opt out.";

const REMINDER_CHANNELS = [
  { value: "sms", label: "Text message", hint: "Skipped for contacts who replied STOP" },
  { value: "email", label: "Email", hint: "Skipped for contacts with no email on file" },
] as const;

const REMINDER_VARIABLES = [
  { name: "{first_name}", description: "Contact's first name" },
  { name: "{last_name}", description: "Contact's last name" },
  { name: "{appointment_date}", description: "Date of the appointment (e.g. March 22, 2026)" },
  { name: "{appointment_time}", description: "Time of the appointment (e.g. 2:30 PM)" },
  { name: "{reschedule_link}", description: "Link for the contact to reschedule" },
  { name: "{meeting_url}", description: "Zoom or Google Meet link for video calls" },
];

export function RemindersSection({ control }: RemindersSectionProps) {
  const reminderEnabled = useWatch({ control, name: "reminderEnabled" });
  const reminderTemplate = useWatch({ control, name: "reminderTemplate" }) ?? "";
  const charCount = reminderTemplate.length;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">Appointment Reminders</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <FormField
          control={control}
          name="reminderEnabled"
          render={({ field }) => (
            <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <FormLabel className="text-base">Enable Reminders</FormLabel>
                <FormDescription>
                  Automatically remind contacts before their appointments
                </FormDescription>
              </div>
              <FormControl>
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              </FormControl>
            </FormItem>
          )}
        />

        {reminderEnabled && (
          <>
            <FormField
              control={control}
              name="reminderOffsets"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Reminder Times</FormLabel>
                  <FormControl>
                    <ReminderOffsetsInput
                      value={field.value}
                      onChange={field.onChange}
                    />
                  </FormControl>
                  <FormDescription>
                    Send reminders at each of these times before the appointment.
                  </FormDescription>
                  {field.value.length === 0 && (
                    <p className="text-xs text-amber-600">
                      Add at least one reminder time for reminders to be sent.
                    </p>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name="reminderChannels"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Reminder Channels</FormLabel>
                  <div className="space-y-2">
                    {REMINDER_CHANNELS.map((channel) => {
                      const checked = field.value.includes(channel.value);
                      return (
                        <div
                          key={channel.value}
                          className="flex items-start gap-3 rounded-lg border p-3"
                        >
                          <FormControl>
                            <Checkbox
                              id={`reminder-channel-${channel.value}`}
                              checked={checked}
                              onCheckedChange={(next) => {
                                field.onChange(
                                  next === true
                                    ? [...field.value, channel.value]
                                    : field.value.filter((c) => c !== channel.value),
                                );
                              }}
                            />
                          </FormControl>
                          <label
                            htmlFor={`reminder-channel-${channel.value}`}
                            className="space-y-0.5 cursor-pointer"
                          >
                            <span className="block text-sm font-medium leading-none">
                              {channel.label}
                            </span>
                            <span className="block text-xs text-muted-foreground">
                              {channel.hint}
                            </span>
                          </label>
                        </div>
                      );
                    })}
                  </div>
                  <FormDescription>
                    Each channel sends its own reminder at every time above.
                  </FormDescription>
                  {field.value.length === 0 && (
                    <p className="text-xs text-amber-600">
                      Pick at least one channel or no reminders will be sent.
                    </p>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name="reminderTemplate"
              render={({ field }) => (
                <FormItem>
                  <div className="flex items-center justify-between">
                    <FormLabel>Custom SMS Template</FormLabel>
                    <span
                      className={`text-xs ${charCount > 160 ? "text-amber-600 font-medium" : "text-muted-foreground"}`}
                    >
                      {charCount} / 160
                      {charCount > 160 ? ` (${Math.ceil(charCount / 153)} segments)` : ""}
                    </span>
                  </div>
                  <FormControl>
                    <Textarea
                      placeholder={DEFAULT_REMINDER_TEMPLATE_PLACEHOLDER}
                      className="min-h-[90px] font-mono text-sm resize-none"
                      value={field.value ?? ""}
                      onChange={(e) => field.onChange(e.target.value || null)}
                    />
                  </FormControl>
                  <FormDescription>
                    Leave blank to use the default message shown in the placeholder above.
                  </FormDescription>
                  <FormMessage />

                  <div className="rounded-md border bg-muted/30 p-3 space-y-1.5">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Available variables
                    </p>
                    <div className="grid gap-1">
                      {REMINDER_VARIABLES.map((v) => (
                        <div key={v.name} className="flex items-baseline gap-2">
                          <code className="text-xs font-mono bg-background border rounded px-1 py-0.5 text-foreground shrink-0">
                            {v.name}
                          </code>
                          <span className="text-xs text-muted-foreground">{v.description}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </FormItem>
              )}
            />
          </>
        )}

        <FormField
          control={control}
          name="confirmationEmailEnabled"
          render={({ field }) => (
            <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <FormLabel className="text-base">Send confirmation email with calendar invite</FormLabel>
                <FormDescription>
                  Emails the contact an .ics invite when they book, so the appointment lands on
                  their calendar
                </FormDescription>
              </div>
              <FormControl>
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              </FormControl>
            </FormItem>
          )}
        />

        <FormField
          control={control}
          name="noshowSmsEnabled"
          render={({ field }) => (
            <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <FormLabel className="text-base">No-Show Re-engagement SMS</FormLabel>
                <FormDescription>
                  Automatically send a rebook SMS when a contact misses their appointment
                </FormDescription>
              </div>
              <FormControl>
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              </FormControl>
            </FormItem>
          )}
        />
      </CardContent>
    </Card>
  );
}
