"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CalendarIcon, Loader2 } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { AppointmentAssigneePicker } from "@/components/calendar/appointment-assignee-picker";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar-lazy";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAgents } from "@/hooks/useAgents";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useCreateAppointment } from "@/hooks/useCreateAppointment";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  APPOINTMENT_FORM_DEFAULTS,
  appointmentFormSchema,
  buildCreateAppointmentRequest,
  DURATION_OPTIONS,
  formatTimeSlot,
  generateTimeSlots,
  type AppointmentFormValues,
} from "@/lib/appointments/appointment-form";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils/date";
import type { Contact } from "@/types";

interface ScheduleAppointmentDialogProps {
  contact: Contact;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const timeSlots = generateTimeSlots();

export function ScheduleAppointmentDialog({
  contact,
  open,
  onOpenChange,
}: ScheduleAppointmentDialogProps) {
  const workspaceId = useWorkspaceId();
  const { can } = useCapabilities();
  const canAssignUsers = can("jobs:write");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [bookableStaffId, setBookableStaffId] = useState<string | null>(null);

  const { data: agentsData, isPending: agentsLoading } = useAgents(workspaceId ?? "", {
    active_only: true,
    page_size: 100,
  });
  const agents = agentsData?.items ?? [];

  const displayName = [contact.first_name, contact.last_name].filter(Boolean).join(" ");

  const form = useForm<AppointmentFormValues>({
    resolver: zodResolver(appointmentFormSchema),
    defaultValues: { ...APPOINTMENT_FORM_DEFAULTS },
  });

  const selectedAgentId = useWatch({ control: form.control, name: "agent_id" });
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId);

  const createAppointmentMutation = useCreateAppointment({
    workspaceId,
    onSuccess: () => {
      form.reset();
      setBookableStaffId(null);
      onOpenChange(false);
    },
  });

  const handleSubmit = (data: AppointmentFormValues) => {
    if (isSubmitting) return;
    setIsSubmitting(true);

    const request = buildCreateAppointmentRequest(data, contact.id);
    if (bookableStaffId) request.bookable_staff_id = bookableStaffId;

    createAppointmentMutation.mutate(request, {
      onSettled: () => setIsSubmitting(false),
    });
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && isSubmitting) return;
    if (!nextOpen) {
      form.reset();
      setBookableStaffId(null);
    }
    onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Book appointment</DialogTitle>
          <DialogDescription>
            Choose a time and visit details for {displayName || "this contact"}.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="date"
                render={({ field }) => (
                  <FormItem className="flex flex-col">
                    <FormLabel>Date *</FormLabel>
                    <Popover>
                      <PopoverTrigger asChild>
                        <FormControl>
                          <Button
                            variant="outline"
                            className={cn(
                              "w-full justify-start px-3 text-left font-normal",
                              !field.value && "text-muted-foreground",
                            )}
                          >
                            <CalendarIcon className="size-4 opacity-60" />
                            {field.value ? (
                              formatDate(field.value, { pattern: "PPP" })
                            ) : (
                              <span>Pick a date</span>
                            )}
                          </Button>
                        </FormControl>
                      </PopoverTrigger>
                      <PopoverContent className="w-auto p-0" align="start">
                        <Calendar
                          mode="single"
                          selected={field.value}
                          onSelect={field.onChange}
                          disabled={(date) => date < new Date(new Date().setHours(0, 0, 0, 0))}
                          initialFocus
                        />
                      </PopoverContent>
                    </Popover>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="time"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Start time *</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select time" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {timeSlots.map((slot) => (
                          <SelectItem key={slot} value={slot}>
                            {formatTimeSlot(slot)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="duration_minutes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Duration</FormLabel>
                  <Select
                    onValueChange={(val) => field.onChange(parseInt(val, 10))}
                    value={field.value.toString()}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select duration" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {DURATION_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value.toString()}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="agent_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Assigned Agent</FormLabel>
                  <Select
                    onValueChange={(val) => field.onChange(val === "none" ? undefined : val)}
                    value={field.value ?? "none"}
                    disabled={agentsLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        {agentsLoading ? (
                          <span className="flex items-center gap-2 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Loading agents...
                          </span>
                        ) : (
                          <SelectValue placeholder="No agent (reminders disabled)" />
                        )}
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="none">No agent</SelectItem>
                      {agents.length === 0 && !agentsLoading ? (
                        <SelectItem value="__empty__" disabled>
                          No active agents configured
                        </SelectItem>
                      ) : (
                        agents.map((agent) => (
                          <SelectItem key={agent.id} value={agent.id}>
                            {agent.name}
                            {agent.reminder_enabled && (
                              <span className="ml-2 text-xs text-muted-foreground">
                                · SMS reminders
                              </span>
                            )}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    {!selectedAgent
                      ? "No automated SMS reminder will be sent."
                      : selectedAgent.reminder_enabled
                        ? `${selectedAgent.name} will send automated SMS reminders.`
                        : `${selectedAgent.name} has SMS reminders turned off.`}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {canAssignUsers && workspaceId ? (
              <AppointmentAssigneePicker
                workspaceId={workspaceId}
                value={bookableStaffId}
                onValueChange={setBookableStaffId}
                disabled={isSubmitting}
                id="contact-appointment-assignee"
              />
            ) : null}

            <FormField
              control={form.control}
              name="service_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Service Type</FormLabel>
                  <FormControl>
                    <Input placeholder="Estimate, consultation, installation..." {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Notes</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Additional notes about this appointment..."
                      className="min-h-[60px]"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isSubmitting ? "Booking..." : "Book appointment"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
