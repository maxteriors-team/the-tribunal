"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { contactsApi } from "@/lib/api/contacts";
import { recurringJobsApi } from "@/lib/api/recurring-jobs";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { RecurrenceFrequency, RecurringJobTemplate } from "@/types";

const FREQUENCIES: { value: RecurrenceFrequency; label: string }[] = [
  { value: "weekly", label: "Weekly" },
  { value: "biweekly", label: "Every 2 weeks" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "yearly", label: "Yearly" },
];

const intString = (min: number) =>
  z
    .string()
    .trim()
    .refine((v) => v !== "" && Number.isInteger(Number(v)) && Number(v) >= min, {
      error: `Enter a whole number ≥ ${min}`,
    });

const schema = z.object({
  contact_id: z.string().min(1, { error: "Pick a customer" }),
  title: z.string().trim().min(1, { error: "Title is required" }),
  frequency: z.enum(["weekly", "biweekly", "monthly", "quarterly", "yearly"]),
  interval: intString(1),
  next_run_at: z.string().min(1, { error: "Pick a first date/time" }),
  duration_minutes: intString(1),
  generate_days_ahead: intString(0),
  description: z.string(),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

const DEFAULT_VALUES: FormValues = {
  contact_id: "",
  title: "",
  frequency: "quarterly",
  interval: "1",
  next_run_at: "",
  duration_minutes: "120",
  generate_days_ahead: "14",
  description: "",
  is_active: true,
};

// `<input type="datetime-local">` works in local time; convert to/from ISO.
function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

function contactLabel(c: {
  id: number;
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
}): string {
  const name = [c.first_name, c.last_name].filter(Boolean).join(" ").trim();
  return name || c.email || `Contact #${c.id}`;
}

interface RecurringJobDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When present the dialog edits this template; otherwise it creates one. */
  template?: RecurringJobTemplate | null;
}

export function RecurringJobDialog({
  open,
  onOpenChange,
  template,
}: RecurringJobDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const isEdit = Boolean(template);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  const contactsQuery = useQuery({
    queryKey: queryKeys.contacts.list(workspaceId ?? "", { page_size: 200 }),
    queryFn: () => contactsApi.list(workspaceId ?? "", { page_size: 200 }),
    enabled: Boolean(workspaceId) && open && !isEdit,
  });

  useEffect(() => {
    if (!open) return;
    form.reset(
      template
        ? {
            contact_id: String(template.contact_id),
            title: template.title,
            frequency: template.frequency,
            interval: String(template.interval),
            next_run_at: isoToLocalInput(template.next_run_at),
            duration_minutes: String(template.duration_minutes),
            generate_days_ahead: String(template.generate_days_ahead),
            description: template.description ?? "",
            is_active: template.is_active,
          }
        : DEFAULT_VALUES
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, template]);

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues): Promise<RecurringJobTemplate> => {
      if (!workspaceId) throw new Error("No workspace selected");
      const nextRunIso = new Date(values.next_run_at).toISOString();
      const common = {
        title: values.title.trim(),
        frequency: values.frequency,
        interval: Number(values.interval),
        duration_minutes: Number(values.duration_minutes),
        generate_days_ahead: Number(values.generate_days_ahead),
        next_run_at: nextRunIso,
        description: values.description.trim() || undefined,
        is_active: values.is_active,
      };
      if (template) {
        return recurringJobsApi.update(workspaceId, template.id, common);
      }
      return recurringJobsApi.create(workspaceId, {
        ...common,
        contact_id: Number(values.contact_id),
      });
    },
    onSuccess: (saved) => {
      toast.success(isEdit ? `Updated ${saved.title}` : `Created ${saved.title}`);
      if (workspaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.recurringJobs.all(workspaceId),
        });
      }
      onOpenChange(false);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save recurring job")),
  });

  const handleOpenChange = (next: boolean) => {
    if (!next && saveMutation.isPending) return;
    onOpenChange(next);
  };

  const contacts = contactsQuery.data?.items ?? [];

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Edit recurring job" : "New recurring job"}
          </DialogTitle>
          <DialogDescription>
            Auto-generate a job on a schedule — the classic maintenance contract.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
            className="space-y-4"
          >
            {!isEdit && (
              <FormField
                control={form.control}
                name="contact_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Customer</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue
                            placeholder={
                              contactsQuery.isLoading
                                ? "Loading customers..."
                                : "Select a customer"
                            }
                          />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {contacts.map((c) => (
                          <SelectItem key={c.id} value={String(c.id)}>
                            {contactLabel(c)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="title"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Title</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. Quarterly HVAC service" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-2 gap-3">
              <FormField
                control={form.control}
                name="frequency"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Repeats</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {FREQUENCIES.map((f) => (
                          <SelectItem key={f.value} value={f.value}>
                            {f.label}
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
                name="interval"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Every N periods</FormLabel>
                    <FormControl>
                      <Input type="number" min="1" step="1" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="next_run_at"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{isEdit ? "Next occurrence" : "First occurrence"}</FormLabel>
                  <FormControl>
                    <Input type="datetime-local" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-2 gap-3">
              <FormField
                control={form.control}
                name="duration_minutes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Duration (min)</FormLabel>
                    <FormControl>
                      <Input type="number" min="1" step="15" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="generate_days_ahead"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Generate days ahead</FormLabel>
                    <FormControl>
                      <Input type="number" min="0" step="1" {...field} />
                    </FormControl>
                    <FormDescription>How early the job appears.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description (optional)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="What the visit covers..."
                      className="min-h-[60px]"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="is_active"
              render={({ field }) => (
                <FormItem className="flex items-center gap-2 space-y-0">
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                  <FormLabel className="!mt-0">Active</FormLabel>
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={saveMutation.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saveMutation.isPending}>
                {saveMutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                {isEdit ? "Save changes" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
