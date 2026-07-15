"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Save } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Form,
  FormControl,
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
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { humanProfilesApi } from "@/lib/api/human-profiles";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { HumanProfile, HumanProfileCreate } from "@/types/human-profile";

const TIMEZONES = [
  { value: "America/New_York", label: "Eastern (ET)" },
  { value: "America/Chicago", label: "Central (CT)" },
  { value: "America/Denver", label: "Mountain (MT)" },
  { value: "America/Los_Angeles", label: "Pacific (PT)" },
  { value: "America/Anchorage", label: "Alaska (AKT)" },
  { value: "Pacific/Honolulu", label: "Hawaii (HT)" },
  { value: "UTC", label: "UTC" },
];

const POLICY_OPTIONS = [
  { value: "auto", label: "Auto-approve" },
  { value: "ask", label: "Ask for approval" },
  { value: "never", label: "Never allow" },
];

const ACTION_TYPES = [
  { key: "book_appointment", label: "Book Appointment" },
  { key: "send_sms", label: "Send SMS" },
  { key: "enroll_campaign", label: "Enroll in Campaign" },
  { key: "apply_tag", label: "Apply Tag" },
] as const;

const policyEnum = z.enum(["auto", "ask", "never"]);

const humanProfileFormSchema = z.object({
  display_name: z.string().min(1, { error: "Display name is required" }).max(255),
  role_title: z.string().max(255).optional().or(z.literal("")),
  phone_number: z.string().max(50).optional().or(z.literal("")),
  email: z
    .union([z.literal(""), z.email({ error: "Invalid email address" })])
    .optional(),
  timezone: z.string().min(1),
  bio: z.string().max(2000).optional().or(z.literal("")),
  default_policy: policyEnum,
  auto_approve_timeout_minutes: z
    .number()
    .int()
    .min(1, { error: "Must be at least 1 minute" })
    .max(10080, { error: "Must be at most 10080 minutes" }),
  auto_reject_timeout_minutes: z
    .number()
    .int()
    .min(1, { error: "Must be at least 1 minute" })
    .max(10080, { error: "Must be at most 10080 minutes" }),
  book_appointment_policy: policyEnum,
  send_sms_policy: policyEnum,
  enroll_campaign_policy: policyEnum,
  apply_tag_policy: policyEnum,
});

type HumanProfileFormValues = z.infer<typeof humanProfileFormSchema>;

interface HumanProfileTabProps {
  agentId: string;
}

export function HumanProfileTab({ agentId }: HumanProfileTabProps) {
  const workspaceId = useWorkspaceId();

  const { data: profile, isPending, error } = useQuery({
    queryKey: queryKeys.agents.humanProfile(workspaceId ?? "", agentId),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return humanProfilesApi.get(workspaceId, agentId);
    },
    enabled: !!workspaceId,
    retry: (failureCount, err) => {
      if (typeof err === "object" && err !== null && "response" in err) {
        const axErr = err as { response?: { status?: number } };
        if (axErr.response?.status === 404) return false;
      }
      return failureCount < 3;
    },
  });

  const is404 =
    error &&
    typeof error === "object" &&
    "response" in error &&
    (error as { response?: { status?: number } }).response?.status === 404;

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <HumanProfileForm
      key={profile?.id ?? "new"}
      agentId={agentId}
      workspaceId={workspaceId}
      profile={profile ?? null}
      is404={!!is404}
    />
  );
}

interface HumanProfileFormProps {
  agentId: string;
  workspaceId: string | null;
  profile: HumanProfile | null;
  is404: boolean;
}

function profileToFormValues(profile: HumanProfile | null): HumanProfileFormValues {
  const policies = profile?.action_policies ?? {};
  const readPolicy = (key: string, fallback: "auto" | "ask" | "never"): "auto" | "ask" | "never" => {
    const v = policies[key];
    return v === "auto" || v === "ask" || v === "never" ? v : fallback;
  };
  const defaultPolicy = (profile?.default_policy === "auto" ||
    profile?.default_policy === "ask" ||
    profile?.default_policy === "never")
    ? profile.default_policy
    : "ask";

  return {
    display_name: profile?.display_name ?? "",
    role_title: profile?.role_title ?? "",
    phone_number: profile?.phone_number ?? "",
    email: profile?.email ?? "",
    timezone: profile?.timezone ?? "America/New_York",
    bio: profile?.bio ?? "",
    default_policy: defaultPolicy,
    auto_approve_timeout_minutes: profile?.auto_approve_timeout_minutes ?? 60,
    auto_reject_timeout_minutes: profile?.auto_reject_timeout_minutes ?? 1440,
    book_appointment_policy: readPolicy("book_appointment", "ask"),
    send_sms_policy: readPolicy("send_sms", "ask"),
    enroll_campaign_policy: readPolicy("enroll_campaign", "ask"),
    apply_tag_policy: readPolicy("apply_tag", "auto"),
  };
}

function HumanProfileForm({ agentId, workspaceId, profile, is404 }: HumanProfileFormProps) {
  const queryClient = useQueryClient();

  const form = useForm<HumanProfileFormValues>({
    resolver: zodResolver(humanProfileFormSchema),
    defaultValues: profileToFormValues(profile),
  });

  const saveMutation = useMutation({
    mutationFn: (data: HumanProfileCreate) => {
      if (!workspaceId) throw new Error("No workspace");
      return humanProfilesApi.upsert(workspaceId, agentId, data);
    },
    onSuccess: () => {
      toast.success("Human profile saved");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agents.humanProfile(workspaceId ?? "", agentId),
      });
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save profile")),
  });

  const handleSave = (data: HumanProfileFormValues) => {
    saveMutation.mutate({
      display_name: data.display_name,
      role_title: data.role_title || undefined,
      phone_number: data.phone_number || undefined,
      email: data.email || undefined,
      timezone: data.timezone,
      bio: data.bio || undefined,
      action_policies: {
        book_appointment: data.book_appointment_policy,
        send_sms: data.send_sms_policy,
        enroll_campaign: data.enroll_campaign_policy,
        apply_tag: data.apply_tag_policy,
      },
      default_policy: data.default_policy,
      auto_approve_timeout_minutes: data.auto_approve_timeout_minutes,
      auto_reject_timeout_minutes: data.auto_reject_timeout_minutes,
    });
  };

  const actionFieldNames = {
    book_appointment: "book_appointment_policy",
    send_sms: "send_sms_policy",
    enroll_campaign: "enroll_campaign_policy",
    apply_tag: "apply_tag_policy",
  } as const;

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(handleSave)} className="space-y-6">
        {is404 && (
          <Card className="border-dashed">
            <CardContent className="py-4">
              <p className="text-sm text-muted-foreground">
                No human profile exists for this agent yet. Fill in the details below to create one.
              </p>
            </CardContent>
          </Card>
        )}

        {/* Basic Info */}
        <Card>
          <CardHeader>
            <CardTitle>Profile Details</CardTitle>
            <CardDescription>
              The human persona your AI agent will represent when interacting with leads
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="display_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Display Name *</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g. Sarah Johnson" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="role_title"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Role Title</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g. Operations Manager" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="phone_number"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Phone Number</FormLabel>
                    <FormControl>
                      <Input placeholder="+1 (555) 123-4567" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input type="email" placeholder="sarah@example.com" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <FormField
              control={form.control}
              name="timezone"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Timezone</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {TIMEZONES.map((tz) => (
                        <SelectItem key={tz.value} value={tz.value}>
                          {tz.label}
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
              name="bio"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Bio</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="A short bio that helps the AI understand who this person is..."
                      rows={3}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        {/* Action Policies */}
        <Card>
          <CardHeader>
            <CardTitle>Action Policies</CardTitle>
            <CardDescription>
              Control which actions the AI can take automatically vs. needing human approval
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <FormField
              control={form.control}
              name="default_policy"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Default Policy</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-48">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {POLICY_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Applied to any action type not explicitly configured below
                  </p>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="space-y-3">
              {ACTION_TYPES.map((at) => (
                <FormField
                  key={at.key}
                  control={form.control}
                  name={actionFieldNames[at.key]}
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between space-y-0">
                      <FormLabel>{at.label}</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger className="w-48">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {POLICY_OPTIONS.map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormItem>
                  )}
                />
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Timeouts */}
        <Card>
          <CardHeader>
            <CardTitle>Timeout Settings</CardTitle>
            <CardDescription>
              How long to wait before auto-approving or expiring pending actions
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="auto_approve_timeout_minutes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Auto-approve timeout (minutes)</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={1}
                        max={10080}
                        className="w-32"
                        value={field.value}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          field.onChange(isNaN(val) ? field.value : val);
                        }}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="auto_reject_timeout_minutes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Auto-reject timeout (minutes)</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={1}
                        max={10080}
                        className="w-32"
                        value={field.value}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          field.onChange(isNaN(val) ? field.value : val);
                        }}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </CardContent>
        </Card>

        {/* Save */}
        <div className="flex justify-end">
          <Button type="submit" disabled={saveMutation.isPending}>
            {saveMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            {profile !== null && !is404 ? "Update Profile" : "Create Profile"}
          </Button>
        </div>
      </form>
    </Form>
  );
}
