"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Save } from "lucide-react";

import { humanProfilesApi } from "@/lib/api/human-profiles";
import type { HumanProfileCreate } from "@/types/human-profile";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getApiErrorMessage } from "@/lib/utils/errors";

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
];

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
  profile: import("@/types/human-profile").HumanProfile | null;
  is404: boolean;
}

function HumanProfileForm({ agentId, workspaceId, profile, is404 }: HumanProfileFormProps) {
  const queryClient = useQueryClient();

  const [displayName, setDisplayName] = useState(profile?.display_name ?? "");
  const [roleTitle, setRoleTitle] = useState(profile?.role_title ?? "");
  const [phoneNumber, setPhoneNumber] = useState(profile?.phone_number ?? "");
  const [email, setEmail] = useState(profile?.email ?? "");
  const [timezone, setTimezone] = useState(profile?.timezone ?? "America/New_York");
  const [bio, setBio] = useState(profile?.bio ?? "");
  const [defaultPolicy, setDefaultPolicy] = useState(profile?.default_policy ?? "ask");
  const [autoApproveTimeout, setAutoApproveTimeout] = useState(profile?.auto_approve_timeout_minutes ?? 60);
  const [autoRejectTimeout, setAutoRejectTimeout] = useState(profile?.auto_reject_timeout_minutes ?? 1440);
  const [actionPolicies, setActionPolicies] = useState<Record<string, string>>({
    book_appointment: "ask",
    send_sms: "ask",
    enroll_campaign: "ask",
    apply_tag: "auto",
    ...profile?.action_policies,
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

  const handleSave = () => {
    if (!displayName.trim()) {
      toast.error("Display name is required");
      return;
    }
    saveMutation.mutate({
      display_name: displayName,
      role_title: roleTitle || undefined,
      phone_number: phoneNumber || undefined,
      email: email || undefined,
      timezone,
      bio: bio || undefined,
      action_policies: actionPolicies,
      default_policy: defaultPolicy,
      auto_approve_timeout_minutes: autoApproveTimeout,
      auto_reject_timeout_minutes: autoRejectTimeout,
    });
  };

  return (
    <div className="space-y-6">
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
            <div className="space-y-2">
              <Label htmlFor="display-name">Display Name *</Label>
              <Input
                id="display-name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="e.g. Sarah Johnson"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="role-title">Role Title</Label>
              <Input
                id="role-title"
                value={roleTitle}
                onChange={(e) => setRoleTitle(e.target.value)}
                placeholder="e.g. Senior Realtor"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="phone-number">Phone Number</Label>
              <Input
                id="phone-number"
                value={phoneNumber}
                onChange={(e) => setPhoneNumber(e.target.value)}
                placeholder="+1 (555) 123-4567"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="sarah@example.com"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="timezone">Timezone</Label>
            <Select value={timezone} onValueChange={setTimezone}>
              <SelectTrigger id="timezone">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIMEZONES.map((tz) => (
                  <SelectItem key={tz.value} value={tz.value}>
                    {tz.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="bio">Bio</Label>
            <Textarea
              id="bio"
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              placeholder="A short bio that helps the AI understand who this person is..."
              rows={3}
            />
          </div>
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
          <div className="space-y-2">
            <Label>Default Policy</Label>
            <Select value={defaultPolicy} onValueChange={setDefaultPolicy}>
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
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
          </div>

          <div className="space-y-3">
            {ACTION_TYPES.map((at) => (
              <div key={at.key} className="flex items-center justify-between">
                <Label>{at.label}</Label>
                <Select
                  value={actionPolicies[at.key] ?? defaultPolicy}
                  onValueChange={(v) =>
                    setActionPolicies((prev) => ({ ...prev, [at.key]: v }))
                  }
                >
                  <SelectTrigger className="w-48">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {POLICY_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
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
            <div className="space-y-2">
              <Label htmlFor="auto-approve">Auto-approve timeout (minutes)</Label>
              <Input
                id="auto-approve"
                type="number"
                min={1}
                max={10080}
                className="w-32"
                value={autoApproveTimeout}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  if (!isNaN(val) && val >= 1) setAutoApproveTimeout(val);
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="auto-reject">Auto-reject timeout (minutes)</Label>
              <Input
                id="auto-reject"
                type="number"
                min={1}
                max={10080}
                className="w-32"
                value={autoRejectTimeout}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  if (!isNaN(val) && val >= 1) setAutoRejectTimeout(val);
                }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Save */}
      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={saveMutation.isPending}>
          {saveMutation.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          {profile !== null && !is404 ? "Update Profile" : "Create Profile"}
        </Button>
      </div>
    </div>
  );
}
