"use client";

import { useState, useMemo } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";
import { formatDate } from "@/lib/utils/date";
import { CalendarIcon, Loader2, Search } from "lucide-react";

import { appointmentsApi, type CreateAppointmentRequest } from "@/lib/api/appointments";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useAgents } from "@/hooks/useAgents";
import { useContacts } from "@/hooks/useContacts";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
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
import { Textarea } from "@/components/ui/textarea";
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
import { cn } from "@/lib/utils";

const appointmentFormSchema = z.object({
  contact_id: z.string().min(1, { error: "Please select a contact" }),
  date: z.date({ message: "Please select a date" }),
  time: z.string().min(1, { error: "Please select a time" }),
  duration_minutes: z.number().min(15).max(480),
  service_type: z.string().optional(),
  notes: z.string().optional(),
  agent_id: z.string().optional(),
});

type AppointmentFormValues = z.infer<typeof appointmentFormSchema>;

interface NewAppointmentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Generate time slots from 8 AM to 6 PM in 30-minute increments
function generateTimeSlots(): string[] {
  const slots: string[] = [];
  for (let hour = 8; hour <= 18; hour++) {
    for (const minute of [0, 30]) {
      if (hour === 18 && minute === 30) continue;
      const h = hour.toString().padStart(2, "0");
      const m = minute.toString().padStart(2, "0");
      slots.push(`${h}:${m}`);
    }
  }
  return slots;
}

const timeSlots = generateTimeSlots();

export function NewAppointmentDialog({ open, onOpenChange }: NewAppointmentDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [contactSearch, setContactSearch] = useState("");

  const { data: agentsData, isPending: agentsLoading } = useAgents(
    workspaceId ?? "",
    { active_only: true, page_size: 100 }
  );
  const agents = agentsData?.items ?? [];

  const { data: contactsData, isPending: contactsLoading } = useContacts(
    workspaceId ?? "",
    { page: 1, page_size: 100, search: contactSearch || undefined }
  );

  const form = useForm<AppointmentFormValues>({
    resolver: zodResolver(appointmentFormSchema),
    defaultValues: {
      contact_id: "",
      duration_minutes: 30,
      service_type: "",
      notes: "",
      agent_id: undefined,
    },
  });

  // Filter contacts by search (server-side search is already applied, client-side filter for instant feedback)
  const filteredContacts = useMemo(() => {
    const items = contactsData?.items ?? [];
    if (!contactSearch) return items;
    const q = contactSearch.toLowerCase();
    return items.filter((c) => {
      const name = [c.first_name, c.last_name].filter(Boolean).join(" ").toLowerCase();
      const phone = c.phone_number?.toLowerCase() ?? "";
      const email = c.email?.toLowerCase() ?? "";
      return name.includes(q) || phone.includes(q) || email.includes(q);
    });
  }, [contactsData?.items, contactSearch]);

  const createAppointmentMutation = useMutation({
    mutationFn: (data: CreateAppointmentRequest) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return appointmentsApi.create(workspaceId, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.appointments.bare(workspaceId ?? "") });
      toast.success("Appointment scheduled successfully!");
      form.reset();
      setContactSearch("");
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Failed to schedule appointment. Please try again."));
    },
    onSettled: () => {
      setIsSubmitting(false);
    },
  });

  const handleSubmit = (data: AppointmentFormValues) => {
    if (isSubmitting) return;
    setIsSubmitting(true);

    const [hours, minutes] = data.time.split(":").map(Number);
    const scheduledAt = new Date(data.date);
    scheduledAt.setHours(hours, minutes, 0, 0);

    const request: CreateAppointmentRequest = {
      contact_id: parseInt(data.contact_id, 10),
      scheduled_at: scheduledAt.toISOString(),
      duration_minutes: data.duration_minutes,
      service_type: data.service_type || undefined,
      notes: data.notes || undefined,
      agent_id: data.agent_id || undefined,
    };

    createAppointmentMutation.mutate(request);
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      form.reset();
      setContactSearch("");
    }
    onOpenChange(open);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
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
                  <div className="space-y-2">
                    <div className="relative">
                      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        placeholder="Search contacts..."
                        value={contactSearch}
                        onChange={(e) => setContactSearch(e.target.value)}
                        className="pl-8"
                      />
                    </div>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                      disabled={contactsLoading}
                    >
                      <FormControl>
                        <SelectTrigger>
                          {contactsLoading ? (
                            <span className="flex items-center gap-2 text-muted-foreground">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              Loading contacts...
                            </span>
                          ) : (
                            <SelectValue placeholder="Select a contact" />
                          )}
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {filteredContacts.length === 0 && !contactsLoading ? (
                          <SelectItem value="__empty__" disabled>
                            No contacts found
                          </SelectItem>
                        ) : (
                          filteredContacts.map((contact) => (
                            <SelectItem key={contact.id} value={String(contact.id)}>
                              {[contact.first_name, contact.last_name].filter(Boolean).join(" ")}
                              {contact.phone_number && (
                                <span className="ml-2 text-xs text-muted-foreground">
                                  {contact.phone_number}
                                </span>
                              )}
                            </SelectItem>
                          ))
                        )}
                      </SelectContent>
                    </Select>
                  </div>
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
                  <FormLabel>Time *</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select time" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {timeSlots.map((slot) => (
                        <SelectItem key={slot} value={slot}>
                          {slot}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
                      <SelectItem value="15">15 minutes</SelectItem>
                      <SelectItem value="30">30 minutes</SelectItem>
                      <SelectItem value="45">45 minutes</SelectItem>
                      <SelectItem value="60">1 hour</SelectItem>
                      <SelectItem value="90">1.5 hours</SelectItem>
                      <SelectItem value="120">2 hours</SelectItem>
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
