"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, Headphones, Loader2, PhoneCall, User } from "lucide-react";
import { useState } from "react";

import { PhoneInput } from "@/components/landing/phone-input";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { agentsApi } from "@/lib/api/agents";
import type { CallMode, InitiateCallRequest } from "@/lib/api/calls";
import { phoneNumbersApi } from "@/lib/api/phone-numbers";
import { settingsApi } from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";
import { useSoftphone } from "@/providers/softphone-provider";

interface OutboundCallDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string | null | undefined;
  /** Contact being dialed. */
  contactName?: string | null;
  contactPhone: string | null | undefined;
  onSubmit: (request: InitiateCallRequest) => void;
  isSubmitting: boolean;
}

const MODE_OPTIONS: {
  value: CallMode;
  label: string;
  description: string;
  Icon: typeof Bot;
}[] = [
  {
    value: "browser",
    label: "Browser headset",
    description: "Talk inside Tribunal without a separate phone line.",
    Icon: Headphones,
  },
  {
    value: "ai",
    label: "AI agent",
    description: "A voice agent runs the call and books from it.",
    Icon: Bot,
  },
  {
    value: "user",
    label: "My phone",
    description: "We ring you first, then connect the contact.",
    Icon: User,
  },
];

/**
 * Pick who talks before dialing a contact: browser operator, AI, or phone callback.
 *
 * Human modes never dial the contact until the operator answers. Browser mode
 * derives its internal SIP destination on the server; the client cannot supply
 * a billable callback target.
 */
export function OutboundCallDialog({
  open,
  onOpenChange,
  workspaceId,
  contactName,
  contactPhone,
  onSubmit,
  isSubmitting,
}: OutboundCallDialogProps) {
  const softphone = useSoftphone();
  const [mode, setMode] = useState<CallMode>("browser");
  const [fromNumberId, setFromNumberId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [callbackNumber, setCallbackNumber] = useState("");
  const [callbackTouched, setCallbackTouched] = useState(false);
  const [browserSubmitting, setBrowserSubmitting] = useState(false);
  const [browserError, setBrowserError] = useState<string | null>(null);

  const { data: phoneNumbersData } = useQuery({
    queryKey: queryKeys.phoneNumbers.list(workspaceId ?? "", { voice_enabled: true }),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.list(workspaceId, { voice_enabled: true });
    },
    enabled: !!workspaceId && open,
  });

  const { data: agentsData } = useQuery({
    queryKey: queryKeys.agents.all(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return agentsApi.list(workspaceId, { active_only: true });
    },
    enabled: !!workspaceId && open,
  });

  const { data: profile } = useQuery({
    queryKey: queryKeys.settings.profile(),
    queryFn: () => settingsApi.getProfile(),
    enabled: open,
  });

  const phoneNumbers = phoneNumbersData?.items ?? [];
  const voiceAgents = (agentsData?.items ?? []).filter(
    (agent) => agent.channel_mode === "voice" || agent.channel_mode === "both",
  );

  // Default each select to the only sensible choice without an effect: derive
  // it, and let an explicit user pick win.
  const selectedFromId = fromNumberId || phoneNumbers[0]?.id || "";
  const selectedAgentId = agentId || voiceAgents[0]?.id || "";
  const resolvedCallback = callbackTouched ? callbackNumber : (profile?.phone_number ?? "");

  const submitting = isSubmitting || browserSubmitting;
  const canSubmit =
    !!contactPhone &&
    !!selectedFromId &&
    !submitting &&
    (mode === "ai" ? !!selectedAgentId : mode === "user" ? !!resolvedCallback : true);

  const handleSubmit = async () => {
    const fromPhone = phoneNumbers.find((p) => p.id === selectedFromId);
    if (!fromPhone || !contactPhone || !workspaceId) return;

    if (mode === "browser") {
      setBrowserSubmitting(true);
      setBrowserError(null);
      try {
        await softphone.startCall({
          workspaceId,
          contactName: contactName || contactPhone,
          toNumber: contactPhone,
          fromPhoneNumber: fromPhone.phone_number,
        });
        onOpenChange(false);
      } catch (error) {
        setBrowserError(
          error instanceof Error ? error.message : "Browser calling could not start.",
        );
      } finally {
        setBrowserSubmitting(false);
      }
      return;
    }

    onSubmit({
      to_number: contactPhone,
      from_phone_number: fromPhone.phone_number,
      contact_phone: contactPhone,
      mode,
      ...(mode === "ai" ? { agent_id: selectedAgentId } : { user_phone_number: resolvedCallback }),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Call {contactName || contactPhone || "contact"}</DialogTitle>
          <DialogDescription>Choose who handles this call before it dials.</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="outbound-from-number">Call from</Label>
            <Select value={selectedFromId} onValueChange={setFromNumberId}>
              <SelectTrigger id="outbound-from-number" className="w-full">
                <SelectValue placeholder="Select a phone number" />
              </SelectTrigger>
              <SelectContent className="max-h-[300px]">
                {phoneNumbers.map((phone) => (
                  <SelectItem key={phone.id} value={phone.id}>
                    {phone.phone_number}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {phoneNumbers.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No voice-enabled phone numbers available.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Who talks</Label>
            <RadioGroup
              value={mode}
              onValueChange={(value) => {
                setMode(value as CallMode);
                setBrowserError(null);
              }}
              className="grid grid-cols-1 gap-3 sm:grid-cols-3"
            >
              {MODE_OPTIONS.map(({ value, label, description, Icon }) => (
                <label
                  key={value}
                  htmlFor={`call-mode-${value}`}
                  className={`flex items-start gap-3 rounded-lg border-2 p-3 cursor-pointer transition-colors ${
                    mode === value
                      ? "border-primary bg-background"
                      : "border-border hover:border-primary/50"
                  }`}
                >
                  <RadioGroupItem value={value} id={`call-mode-${value}`} />
                  <div className="flex-1">
                    <div className="flex items-center gap-2 font-medium">
                      <Icon className="size-4" aria-hidden="true" />
                      {label}
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{description}</p>
                  </div>
                </label>
              ))}
            </RadioGroup>
          </div>

          {mode === "ai" ? (
            <div className="space-y-2">
              <Label htmlFor="outbound-agent">Voice agent</Label>
              <Select value={selectedAgentId} onValueChange={setAgentId}>
                <SelectTrigger id="outbound-agent" className="w-full">
                  <SelectValue placeholder="Select an agent" />
                </SelectTrigger>
                <SelectContent className="max-h-[300px]">
                  {voiceAgents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {voiceAgents.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No active voice agents. Switch to &quot;Browser headset&quot; to take this call
                  yourself.
                </p>
              )}
            </div>
          ) : mode === "user" ? (
            <div className="space-y-2">
              <Label htmlFor="outbound-callback">Ring me at</Label>
              <PhoneInput
                id="outbound-callback"
                value={resolvedCallback}
                onChange={(value) => {
                  setCallbackTouched(true);
                  setCallbackNumber(value);
                }}
              />
              <p className="text-sm text-muted-foreground">
                {resolvedCallback
                  ? "We call you first, then dial the contact and connect you."
                  : "Add a phone number to your profile, or enter a workspace number."}
              </p>
            </div>
          ) : (
            <div className="rounded-lg border p-3">
              <p className="text-sm font-medium">Desktop Chrome and a headset</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Tribunal will ask for microphone access, ring this browser, then dial the contact
                after you answer.
              </p>
            </div>
          )}

          {browserError && (
            <p role="alert" className="text-sm text-destructive">
              {browserError}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={() => void handleSubmit()} disabled={!canSubmit}>
            {submitting ? (
              <>
                <Loader2
                  className="mr-2 size-4 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
                Connecting...
              </>
            ) : (
              <>
                {mode === "browser" ? (
                  <Headphones className="mr-2 size-4" aria-hidden="true" />
                ) : (
                  <PhoneCall className="mr-2 size-4" aria-hidden="true" />
                )}
                {mode === "ai"
                  ? "Start AI call"
                  : mode === "browser"
                    ? "Connect headset & call"
                    : "Call me first"}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
