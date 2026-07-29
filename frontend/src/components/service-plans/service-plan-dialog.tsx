"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
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
import { servicePlansApi } from "@/lib/api/service-plans";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type {
  RecurrenceFrequency,
  ServicePlan,
  ServicePlanType,
} from "@/types";

const FREQUENCIES: { value: RecurrenceFrequency; label: string }[] = [
  { value: "weekly", label: "Weekly" },
  { value: "biweekly", label: "Every 2 weeks" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "yearly", label: "Yearly" },
];

const PLAN_TYPES: { value: ServicePlanType; label: string }[] = [
  { value: "lighting_care_plan", label: "Lighting Care Plan" },
  { value: "christmas_lights", label: "Christmas lights" },
  { value: "maintenance", label: "Maintenance contract" },
];

/**
 * Sensible starting schedule per plan type, matching what the provisioner
 * creates on signup: a quarterly care visit, a once-a-year seasonal visit, and
 * the generic quarterly maintenance contract.
 */
const PLAN_TYPE_DEFAULTS: Record<
  ServicePlanType,
  { frequency: RecurrenceFrequency; duration_minutes: string; generate_days_ahead: string }
> = {
  lighting_care_plan: {
    frequency: "quarterly",
    duration_minutes: "90",
    generate_days_ahead: "14",
  },
  christmas_lights: {
    frequency: "yearly",
    duration_minutes: "240",
    generate_days_ahead: "30",
  },
  maintenance: {
    frequency: "quarterly",
    duration_minutes: "120",
    generate_days_ahead: "14",
  },
};

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
  plan_type: z.enum(["lighting_care_plan", "christmas_lights", "maintenance"]),
  care_plan_tier: z.string(),
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
  plan_type: "maintenance",
  care_plan_tier: "",
  frequency: PLAN_TYPE_DEFAULTS.maintenance.frequency,
  interval: "1",
  next_run_at: "",
  duration_minutes: PLAN_TYPE_DEFAULTS.maintenance.duration_minutes,
  generate_days_ahead: PLAN_TYPE_DEFAULTS.maintenance.generate_days_ahead,
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

interface ServicePlanDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When present the dialog edits this plan; otherwise it creates one. */
  plan?: ServicePlan | null;
}

export function ServicePlanDialog({
  open,
  onOpenChange,
  plan,
}: ServicePlanDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const isEdit = Boolean(plan);
  const [contactSearch, setContactSearch] = useState("");

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  // Server-side contact search keeps the picker usable in workspaces with more
  // than the endpoint's 100-per-page cap — the operator narrows by name/email
  // instead of the client trying to load every contact at once.
  const contactsParams = {
    page: 1,
    page_size: 100,
    search: contactSearch.trim() || undefined,
  };
  const contactsQuery = useQuery({
    queryKey: queryKeys.contacts.list(workspaceId ?? "", contactsParams),
    queryFn: () => contactsApi.list(workspaceId ?? "", contactsParams),
    enabled: Boolean(workspaceId) && open && !isEdit,
  });

  useEffect(() => {
    if (!open) return;
    form.reset(
      plan
        ? {
            contact_id: String(plan.contact_id),
            title: plan.title,
            plan_type: plan.plan_type,
            care_plan_tier: plan.care_plan_tier ?? "",
            frequency: plan.frequency,
            interval: String(plan.interval),
            next_run_at: isoToLocalInput(plan.next_run_at),
            duration_minutes: String(plan.duration_minutes),
            generate_days_ahead: String(plan.generate_days_ahead),
            description: plan.description ?? "",
            is_active: plan.is_active,
          }
        : DEFAULT_VALUES
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, plan]);

  const planType = form.watch("plan_type");

  /**
   * Switching plan type re-seeds the schedule to that plan's shape. Only done
   * when creating: silently rewriting an existing plan's cadence would move a
   * client's visits out from under them.
   */
  const handlePlanTypeChange = (next: string) => {
    const value = next as ServicePlanType;
    form.setValue("plan_type", value, { shouldDirty: true });
    if (value !== "lighting_care_plan") form.setValue("care_plan_tier", "");
    if (isEdit) return;
    const defaults = PLAN_TYPE_DEFAULTS[value];
    form.setValue("frequency", defaults.frequency);
    form.setValue("duration_minutes", defaults.duration_minutes);
    form.setValue("generate_days_ahead", defaults.generate_days_ahead);
  };

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues): Promise<ServicePlan> => {
      if (!workspaceId) throw new Error("No workspace selected");
      const nextRunIso = new Date(values.next_run_at).toISOString();
      const tier = values.care_plan_tier.trim();
      const common = {
        title: values.title.trim(),
        plan_type: values.plan_type,
        // Only a Care Plan carries a tier; the API rejects one anywhere else.
        care_plan_tier:
          values.plan_type === "lighting_care_plan" && tier ? tier : null,
        frequency: values.frequency,
        interval: Number(values.interval),
        duration_minutes: Number(values.duration_minutes),
        generate_days_ahead: Number(values.generate_days_ahead),
        next_run_at: nextRunIso,
        description: values.description.trim() || undefined,
        is_active: values.is_active,
      };
      if (plan) {
        return servicePlansApi.update(workspaceId, plan.id, common);
      }
      return servicePlansApi.create(workspaceId, {
        ...common,
        contact_id: Number(values.contact_id),
      });
    },
    onSuccess: (saved) => {
      toast.success(isEdit ? `Updated ${saved.title}` : `Created ${saved.title}`);
      if (workspaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.servicePlans.all(workspaceId),
        });
      }
      setContactSearch("");
      onOpenChange(false);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save service plan")),
  });

  const handleOpenChange = (next: boolean) => {
    if (!next && saveMutation.isPending) return;
    if (!next) setContactSearch("");
    onOpenChange(next);
  };

  const contacts = contactsQuery.data?.items ?? [];

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Edit service plan" : "New service plan"}
          </DialogTitle>
          <DialogDescription>
            Put a client on recurring work. Each plan auto-generates its next
            visit on the schedule.
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
                    <Input
                      placeholder="Search customers by name or email…"
                      value={contactSearch}
                      onChange={(event) => setContactSearch(event.target.value)}
                      className="mb-2"
                    />
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
                        {contacts.length === 0 ? (
                          <div className="px-2 py-1.5 text-sm text-muted-foreground">
                            {contactsQuery.isLoading
                              ? "Loading customers…"
                              : "No customers found"}
                          </div>
                        ) : (
                          contacts.map((c) => (
                            <SelectItem key={c.id} value={String(c.id)}>
                              {contactLabel(c)}
                            </SelectItem>
                          ))
                        )}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="plan_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Plan type</FormLabel>
                  <Select
                    onValueChange={handlePlanTypeChange}
                    value={field.value}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {PLAN_TYPES.map((type) => (
                        <SelectItem key={type.value} value={type.value}>
                          {type.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Care Plans and Christmas signups are normally created
                    automatically when a client approves their proposal.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {planType === "lighting_care_plan" && (
              <FormField
                control={form.control}
                name="care_plan_tier"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Care Plan tier (optional)</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g. gold" {...field} />
                    </FormControl>
                    <FormDescription>
                      The tier key from your pricing config, shown as a badge on
                      the plan.
                    </FormDescription>
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
                    <Input
                      placeholder={
                        planType === "christmas_lights"
                          ? "e.g. Christmas Lighting — Install"
                          : "e.g. Quarterly HVAC service"
                      }
                      {...field}
                    />
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
                  <FormLabel>
                    {isEdit ? "Next occurrence" : "First occurrence"}
                  </FormLabel>
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
