"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, Loader2, PhoneCall, User } from "lucide-react";
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
 * Pick who talks before dialing a contact: an AI voice agent, or the operator.
 *
 * User mode never dials the contact until the operator's own phone is answered,
 * so nobody is called into silence. The callback number is editable but the
 * backend only accepts allowlisted numbers (your profile phone, the workspace
 * transfer destination, or a workspace number).
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
  const [mode, setMode] = useState<CallMode>("ai");
  const [fromNumberId, setFromNumberId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [callbackNumber, setCallbackNumber] = useState("");
  const [callbackTouched, setCallbackTouched] = useState(false);

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
  const resolvedCallback = callbackTouched
    ? callbackNumber
    : (profile?.phone_number ?? "");

  const canSubmit =
    !!contactPhone &&
    !!selectedFromId &&
    !isSubmitting &&
    (mode === "ai" ? !!selectedAgentId : !!resolvedCallback);

  const handleSubmit = () => {
    const fromPhone = phoneNumbers.find((p) => p.id === selectedFromId);
    if (!fromPhone || !contactPhone) return;

    onSubmit({
      to_number: contactPhone,
      from_phone_number: fromPhone.phone_number,
      contact_phone: contactPhone,
      mode,
      ...(mode === "ai"
        ? { agent_id: selectedAgentId }
        : { user_phone_number: resolvedCallback }),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Call {contactName || contactPhone || "contact"}</DialogTitle>
          <DialogDescription>
            Choose who handles this call before it dials.
          </DialogDescription>
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
              onValueChange={(value) => setMode(value as CallMode)}
              className="grid grid-cols-2 gap-3"
            >
              {MODE_OPTIONS.map(({ value, label, description, Icon }) => (
                <label
                  key={value}
                  htmlFor={`call-mode-${value}`}
                  className={`flex items-start gap-3 rounded-lg border-2 p-3 cursor-pointer transition-colors ${
                    mode === value
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/50"
                  }`}
                >
                  <RadioGroupItem value={value} id={`call-mode-${value}`} />
                  <div className="flex-1">
                    <div className="flex items-center gap-2 font-medium">
                      <Icon className="size-4" />
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
                  No active voice agents. Switch to &quot;My phone&quot; to take this
                  call yourself.
                </p>
              )}
            </div>
          ) : (
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
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                Calling...
              </>
            ) : (
              <>
                <PhoneCall className="mr-2 size-4" />
                {mode === "ai" ? "Start AI call" : "Call me first"}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
