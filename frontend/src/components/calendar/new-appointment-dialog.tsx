"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CalendarIcon, Loader2 } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import * as z from "zod";

import { AppointmentAssigneePicker } from "@/components/calendar/appointment-assignee-picker";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar-lazy";
import { FormContactPicker } from "@/components/ui/contact-combobox";
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
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
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
} from "@/lib/appointments/appointment-form";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils/date";

const newAppointmentFormSchema = z.intersection(
  appointmentFormSchema,
  z.object({ contact_id: z.string().min(1, { error: "Please select a contact" }) }),
);

type NewAppointmentFormValues = z.infer<typeof newAppointmentFormSchema>;

interface NewAppointmentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const timeSlots = generateTimeSlots();

export function NewAppointmentDialog({ open, onOpenChange }: NewAppointmentDialogProps) {
  const workspaceId = useWorkspaceId();
  const { can } = useCapabilities();
  const canAssignUsers = can("jobs:write");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [bookableStaffId, setBookableStaffId] = useState<string | null>(null);

  // Everything this form reads — the agent list and the client roster behind
  // the picker — is `crm:read` on the backend.
  const canReadCrm = can("crm:read");
  // `GET /agents` is `crm:read`, and the calendar keeps this dialog mounted
  // while it is closed — so an unconditional fetch cost every operator a
  // request per page load and earned a field technician a 403.
  const agentsEnabled = open && canReadCrm && !!workspaceId;
  const { data: agentsData, isPending } = useAgents(
    agentsEnabled ? (workspaceId ?? "") : "",
    { active_only: true, page_size: 100 }
  );
  const agents = agentsData?.items ?? [];
  // A disabled query stays `pending` forever; only call it loading when it can
  // actually resolve, so the picker never sticks on "Loading agents...".
  const agentsLoading = agentsEnabled && isPending;

  const form = useForm<NewAppointmentFormValues>({
    resolver: zodResolver(newAppointmentFormSchema),
    defaultValues: {
      ...APPOINTMENT_FORM_DEFAULTS,
      contact_id: "",
    },
  });
  const anytime = useWatch({ control: form.control, name: "anytime" });
  const createAppointmentMutation = useCreateAppointment({
    workspaceId,
    onSuccess: () => {
      form.reset();
      setBookableStaffId(null);
      onOpenChange(false);
    },
  });

  const handleSubmit = (data: NewAppointmentFormValues) => {
    if (isSubmitting) return;
    setIsSubmitting(true);

    const request = buildCreateAppointmentRequest(
      data,
      parseInt(data.contact_id, 10),
    );
    if (bookableStaffId) request.bookable_staff_id = bookableStaffId;

    createAppointmentMutation.mutate(request, {
      onSettled: () => setIsSubmitting(false),
    });
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      form.reset();
      setBookableStaffId(null);
    }
    onOpenChange(open);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>New Appointment</DialogTitle>
          <DialogDescription>
            Schedule a new appointment for a contact.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            {/* Contact selector */}
            <FormField
              control={form.control}
              name="contact_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Contact *</FormLabel>
                  {/* Disabled without `crm:read`: the dialog autofocuses this
                      field on open, and the picker searches the workspace
                      contact list on focus — a 403 for a field technician.
                      Disabling it blocks that focus, so no request is made. */}
                  <FormContactPicker
                    workspaceId={workspaceId}
                    value={field.value}
                    onChange={(contactId) => field.onChange(contactId)}
                    disabled={!canReadCrm}
                    placeholder={
                      canReadCrm
                        ? "Search contacts by name, phone, or email…"
                        : "You do not have access to the client list"
                    }
                  />
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Date */}
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
                            "w-full pl-3 text-left font-normal",
                            !field.value && "text-muted-foreground"
                          )}
                        >
                          {field.value ? (
                            formatDate(field.value, { pattern: "PPP" })
                          ) : (
                            <span>Pick a date</span>
                          )}
                          <CalendarIcon className="ml-auto h-4 w-4 opacity-50" />
                        </Button>
                      </FormControl>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-0" align="start">
                      <Calendar
                        mode="single"
                        selected={field.value}
                        onSelect={field.onChange}
                        disabled={(date) =>
                          date < new Date(new Date().setHours(0, 0, 0, 0))
                        }
                        initialFocus
                      />
                    </PopoverContent>
                  </Popover>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Time */}
            <FormField
              control={form.control}
              name="time"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Time{anytime ? "" : " *"}</FormLabel>
                  <div className="flex gap-2">
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                      disabled={anytime}
                    >
                      <FormControl>
                        <SelectTrigger>
                          {anytime ? (
                            <span>Any time</span>
                          ) : (
                            <SelectValue placeholder="Select time" />
                          )}
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
                    <Button
                      type="button"
                      variant={anytime ? "default" : "outline"}
                      aria-pressed={anytime}
                      onClick={() => {
                        form.setValue("anytime", !anytime, { shouldValidate: true });
                        if (!anytime) form.clearErrors("time");
                      }}
                    >
                      Any time
                    </Button>
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Duration */}
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

            {/* Agent */}
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
                      {agents.map((agent) => (
                        <SelectItem key={agent.id} value={agent.id}>
                          {agent.name}
                          {agent.reminder_enabled && (
                            <span className="ml-2 text-xs text-muted-foreground">· SMS reminders</span>
                          )}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Selecting an agent enables automated SMS reminders.
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
                id="new-appointment-assignee"
              />
            ) : null}

            {/* Service Type */}
            <FormField
              control={form.control}
              name="service_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Service Type</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g., Consultation, Follow-up" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Notes */}
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
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isSubmitting ? "Scheduling..." : "Schedule"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
