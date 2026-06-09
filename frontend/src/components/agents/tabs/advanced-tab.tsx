import { ChevronDown, Phone } from "lucide-react";
import { type UseFormReturn, useWatch } from "react-hook-form";

import type { EditAgentFormValues } from "@/components/agents/agent-edit-schema";
import { PostMeetingSmsSection } from "@/components/agents/tabs/advanced/post-meeting-sms-section";
import { RemindersSection } from "@/components/agents/tabs/advanced/reminders-section";
import { StaffRoutingSection } from "@/components/agents/tabs/advanced/staff-routing-section";
import { TextSettingsSection } from "@/components/agents/tabs/advanced/text-settings-section";
import { TransferSection } from "@/components/agents/tabs/advanced/transfer-section";
import { ValueReinforcementSection } from "@/components/agents/tabs/advanced/value-reinforcement-section";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { formatDate } from "@/lib/utils/date";
import type { Agent } from "@/types/agent";

interface AdvancedTabProps {
  form: UseFormReturn<EditAgentFormValues>;
  voiceProvider: string;
  agent: Agent;
}

export function AdvancedTab({ form, voiceProvider, agent }: AdvancedTabProps) {
  const { control } = form;
  const noshowReengagementEnabled = useWatch({ control, name: "noshowReengagementEnabled" });
  const neverBookedReengagementEnabled = useWatch({
    control,
    name: "neverBookedReengagementEnabled",
  });
  const ivrNavigationEnabled = useWatch({ control, name: "enableIvrNavigation" });

  return (
    <>
      <TextSettingsSection control={control} />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Calendar Integration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <FormField
            control={control}
            name="calcomEventTypeId"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Cal.com Event Type ID</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    placeholder="Enter Event Type ID"
                    value={field.value ?? ""}
                    onChange={(e) => {
                      const value = e.target.value ? parseInt(e.target.value) : null;
                      field.onChange(value);
                    }}
                  />
                </FormControl>
                <FormDescription>
                  Optional: Connect to Cal.com for appointment booking. Used directly when the
                  assignment strategy below is &ldquo;Single calendar&rdquo;.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </CardContent>
      </Card>

      <StaffRoutingSection control={control} workspaceId={agent.workspace_id} agentId={agent.id} />

      <RemindersSection control={control} />

      <TransferSection control={control} />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">No-Show Re-engagement Sequence</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <FormField
            control={control}
            name="noshowReengagementEnabled"
            render={({ field }) => (
              <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                <div className="space-y-0.5">
                  <FormLabel className="text-base">Enable Multi-Day Re-engagement</FormLabel>
                  <FormDescription>
                    Automatically send Day-3 and Day-7 SMS messages to no-show contacts to win them
                    back
                  </FormDescription>
                </div>
                <FormControl>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </FormControl>
              </FormItem>
            )}
          />

          {noshowReengagementEnabled && (
            <>
              <FormField
                control={control}
                name="noshowDay3Template"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Day 3 Message</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Message sent 3 days after no-show — e.g. Hey {first_name}, we'd still love to connect. Want to reschedule? {reschedule_link}"
                        className="min-h-[90px] font-mono text-sm resize-none"
                        value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value || null)}
                      />
                    </FormControl>
                    <FormDescription>
                      Sent ~3 days after the no-show. Leave blank to use the default message.
                      Supports{" "}
                      <code className="text-xs font-mono bg-muted rounded px-1">
                        {"{first_name}"}
                      </code>{" "}
                      and{" "}
                      <code className="text-xs font-mono bg-muted rounded px-1">
                        {"{reschedule_link}"}
                      </code>
                      .
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={control}
                name="noshowDay7Template"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Day 7 Message</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Value-first offer message — e.g. Hi {first_name}, we're offering 300 free video ads to qualified businesses. Still interested? Book here: {reschedule_link}"
                        className="min-h-[90px] font-mono text-sm resize-none"
                        value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value || null)}
                      />
                    </FormControl>
                    <FormDescription>
                      Sent ~7 days after the no-show (only if the Day-3 message was already sent).
                      Leave blank to use the default message.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Never-Booked Re-engagement</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <FormField
            control={control}
            name="neverBookedReengagementEnabled"
            render={({ field }) => (
              <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                <div className="space-y-0.5">
                  <FormLabel className="text-base">Enable Never-Booked Re-engagement</FormLabel>
                  <FormDescription>
                    Send a follow-up to contacts who replied but never booked an appointment
                  </FormDescription>
                </div>
                <FormControl>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </FormControl>
              </FormItem>
            )}
          />

          {neverBookedReengagementEnabled && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={control}
                  name="neverBookedDelayDays"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Days before re-engaging</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={1}
                          max={365}
                          placeholder="7"
                          value={field.value}
                          onChange={(e) => field.onChange(parseInt(e.target.value) || 7)}
                        />
                      </FormControl>
                      <FormDescription>How many days of inactivity before sending</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={control}
                  name="neverBookedMaxAttempts"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Max re-engagement attempts</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={1}
                          max={10}
                          placeholder="2"
                          value={field.value}
                          onChange={(e) => field.onChange(parseInt(e.target.value) || 2)}
                        />
                      </FormControl>
                      <FormDescription>Maximum messages per contact</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={control}
                name="neverBookedTemplate"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Re-engagement Message</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Hi {first_name}, just checking in — we're still offering our free video ads strategy session. Book your spot: {booking_link}"
                        className="min-h-[90px] font-mono text-sm resize-none"
                        value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value || null)}
                      />
                    </FormControl>
                    <FormDescription>
                      Leave blank to use the default message. Supports{" "}
                      <code className="text-xs font-mono bg-muted rounded px-1">
                        {"{first_name}"}
                      </code>{" "}
                      and{" "}
                      <code className="text-xs font-mono bg-muted rounded px-1">
                        {"{booking_link}"}
                      </code>
                      .
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </>
          )}
        </CardContent>
      </Card>

      <ValueReinforcementSection control={control} />

      <PostMeetingSmsSection control={control} />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Experiment Auto-Evaluation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <FormField
            control={control}
            name="autoEvaluate"
            render={({ field }) => (
              <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                <div className="space-y-0.5">
                  <FormLabel className="text-base">Auto-Evaluate Experiments</FormLabel>
                  <FormDescription>
                    Automatically declare winners and eliminate underperformers when statistical
                    confidence is reached (95% threshold)
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

      {voiceProvider === "grok" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">IVR Navigation Settings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Configure how your agent navigates automated phone menus (IVR systems)
            </p>

            <FormField
              control={control}
              name="enableIvrNavigation"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                  <div className="space-y-0.5">
                    <FormLabel className="text-base">Enable IVR Navigation</FormLabel>
                    <FormDescription>
                      Allow agent to detect and navigate through phone menus using DTMF tones
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                </FormItem>
              )}
            />

            {ivrNavigationEnabled && (
              <>
                <FormField
                  control={control}
                  name="ivrNavigationGoal"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Navigation Goal</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="e.g., Reach sales department, Speak to a human representative"
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        What should the agent try to achieve when navigating IVR menus?
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <Collapsible>
                  <CollapsibleTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="w-full justify-between"
                    >
                      <span className="flex items-center gap-2">
                        <Phone className="h-4 w-4" />
                        Advanced IVR Timing
                      </span>
                      <ChevronDown className="h-4 w-4" />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="space-y-4 pt-4">
                    <FormField
                      control={control}
                      name="ivrSilenceDurationMs"
                      render={({ field }) => (
                        <FormItem>
                          <div className="flex items-center justify-between">
                            <FormLabel>Silence Duration</FormLabel>
                            <span className="text-sm font-medium">{field.value}ms</span>
                          </div>
                          <FormControl>
                            <Slider
                              min={1000}
                              max={10000}
                              step={500}
                              value={[field.value]}
                              onValueChange={(value) => field.onChange(value[0])}
                              className="w-full"
                            />
                          </FormControl>
                          <FormDescription>
                            How long to wait for menu to complete before responding
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={control}
                      name="ivrPostDtmfCooldownMs"
                      render={({ field }) => (
                        <FormItem>
                          <div className="flex items-center justify-between">
                            <FormLabel>Post-DTMF Cooldown</FormLabel>
                            <span className="text-sm font-medium">{field.value}ms</span>
                          </div>
                          <FormControl>
                            <Slider
                              min={0}
                              max={10000}
                              step={500}
                              value={[field.value]}
                              onValueChange={(value) => field.onChange(value[0])}
                              className="w-full"
                            />
                          </FormControl>
                          <FormDescription>
                            Minimum wait time after pressing a button before pressing another
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={control}
                      name="ivrLoopThreshold"
                      render={({ field }) => (
                        <FormItem>
                          <div className="flex items-center justify-between">
                            <FormLabel>Loop Detection Threshold</FormLabel>
                            <span className="text-sm font-medium">{field.value} repeats</span>
                          </div>
                          <FormControl>
                            <Slider
                              min={1}
                              max={10}
                              step={1}
                              value={[field.value]}
                              onValueChange={(value) => field.onChange(value[0])}
                              className="w-full"
                            />
                          </FormControl>
                          <FormDescription>
                            Number of menu repeats before trying alternative options
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </CollapsibleContent>
                </Collapsible>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Agent Statistics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <div className="rounded-md border p-3">
              <p className="text-xs text-muted-foreground">Provider</p>
              <p className="text-sm font-medium capitalize">{agent.voice_provider}</p>
            </div>
            <div className="rounded-md border p-3">
              <p className="text-xs text-muted-foreground">Created</p>
              <p className="text-sm font-medium">{formatDate(agent.created_at)}</p>
            </div>
            <div className="rounded-md border p-3">
              <p className="text-xs text-muted-foreground">Last Updated</p>
              <p className="text-sm font-medium">{formatDate(agent.updated_at)}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
