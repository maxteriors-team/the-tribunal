"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, Loader2, PhoneForwarded, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { agentsApi } from "@/lib/api/agents";
import { phoneNumbersApi, type InboundCallConfigRequest } from "@/lib/api/phone-numbers";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { PhoneNumber } from "@/types";

const E164_PATTERN = /^\+[1-9]\d{7,14}$/;
const EDITABLE_READINESS_CHECKS = new Set([
  "agent",
  "agent_provider",
  "fallback_number",
  "transfer_destination",
]);

export function InboundCallingDialog({
  workspaceId,
  number,
  trigger,
}: {
  workspaceId: string;
  number: PhoneNumber;
  trigger: React.ReactNode;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [agentId, setAgentId] = useState(number.assigned_agent_id ?? "");
  const [fallbackNumber, setFallbackNumber] = useState("");
  const [transferNumber, setTransferNumber] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);

  const readinessKey = queryKeys.phoneNumbers.inboundReadiness(workspaceId, number.id);
  const readinessQuery = useQuery({
    queryKey: readinessKey,
    queryFn: () => phoneNumbersApi.inboundReadiness(workspaceId, number.id),
    enabled: open,
    retry: false,
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents.all(workspaceId),
    queryFn: () => agentsApi.list(workspaceId, { active_only: true, page_size: 100 }),
    enabled: open,
  });

  const readiness = readinessQuery.data;
  const enabled = readiness?.enabled ?? number.inbound_ai_enabled;
  const agents = (agentsQuery.data?.items ?? []).filter(
    (agent) =>
      agent.is_active &&
      ["voice", "both"].includes(agent.channel_mode) &&
      agent.voice_provider === "openai" &&
      Boolean(agent.voice_id),
  );
  const selectedAgentId = agentId || readiness?.assigned_agent_id || "";

  const mutation = useMutation({
    mutationFn: (data: InboundCallConfigRequest) =>
      phoneNumbersApi.configureInbound(workspaceId, number.id, data),
    onSuccess: (data) => {
      queryClient.setQueryData(readinessKey, data);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.phoneNumbers.all(workspaceId),
      });
      setFallbackNumber("");
      setTransferNumber("");
      setAcknowledged(false);
      toast.success(
        data.enabled ? "AI inbound answering enabled" : "AI inbound answering disabled",
      );
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Could not update AI inbound answering"));
    },
  });

  const resetForm = () => {
    setAgentId(number.assigned_agent_id ?? "");
    setFallbackNumber("");
    setTransferNumber("");
    setAcknowledged(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) resetForm();
    setOpen(nextOpen);
  };

  const fallbackInvalid = Boolean(fallbackNumber && !E164_PATTERN.test(fallbackNumber));
  const transferInvalid = Boolean(transferNumber && !E164_PATTERN.test(transferNumber));
  const fallbackReady = fallbackNumber ? !fallbackInvalid : Boolean(readiness?.fallback_configured);
  const transferReady = transferNumber
    ? !transferInvalid
    : Boolean(readiness?.transfer_destination_configured);
  const selectedAgentReady = agents.some((agent) => agent.id === selectedAgentId);
  const staticChecksReady = readiness?.checks.every(
    (check) => check.ready || EDITABLE_READINESS_CHECKS.has(check.code),
  );
  const canEnable = Boolean(
    readiness &&
    selectedAgentReady &&
    staticChecksReady &&
    fallbackReady &&
    transferReady &&
    (enabled || acknowledged),
  );
  const displayedChecks = readiness?.checks.map((check) => {
    if (["agent", "agent_provider"].includes(check.code)) {
      return { ...check, ready: selectedAgentReady, message: "OpenAI voice agent selected." };
    }
    if (check.code === "fallback_number") {
      return {
        ...check,
        ready: fallbackReady,
        message: fallbackReady
          ? "Emergency fallback is configured."
          : fallbackInvalid
            ? "Enter the emergency fallback in E.164 format."
            : check.message,
      };
    }
    if (check.code === "transfer_destination") {
      return {
        ...check,
        ready: transferReady,
        message: transferReady
          ? "Human transfer is configured."
          : transferInvalid
            ? "Enter the human transfer number in E.164 format."
            : check.message,
      };
    }
    return check;
  });

  const enable = () => {
    const data: InboundCallConfigRequest = {
      enabled: true,
      assigned_agent_id: selectedAgentId,
    };
    if (fallbackNumber) data.fallback_number = fallbackNumber;
    if (transferNumber) data.transfer_destination_number = transferNumber;
    mutation.mutate(data);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bot className="size-5" aria-hidden="true" />
            AI inbound answering
          </DialogTitle>
          <DialogDescription>
            Configure immediate AI answering for {formatPhoneNumber(number.phone_number)}. This does
            not enable browser ringing or raw call recording.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-1">
          <div className="flex items-center justify-between gap-4 rounded-md border p-3">
            <div>
              <p className="text-sm font-medium">Current status</p>
              <p className="text-sm text-muted-foreground">
                {enabled ? "AI answers inbound calls." : "AI answering is off."}
              </p>
            </div>
            <Badge variant={enabled ? "default" : "secondary"}>{enabled ? "Enabled" : "Off"}</Badge>
          </div>

          <div className="space-y-2">
            <Label htmlFor={`inbound-agent-${number.id}`}>Voice agent</Label>
            <Select
              value={selectedAgentId}
              onValueChange={setAgentId}
              disabled={agentsQuery.isPending}
            >
              <SelectTrigger id={`inbound-agent-${number.id}`}>
                <SelectValue placeholder="Choose an OpenAI voice agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {agentsQuery.isError && (
              <p className="text-sm text-destructive" role="alert">
                Voice agents could not be loaded. Close this dialog and retry.
              </p>
            )}
            {!agentsQuery.isPending && !agentsQuery.isError && agents.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Create an active OpenAI voice agent before enabling inbound answering.
              </p>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor={`inbound-fallback-${number.id}`}>Emergency fallback</Label>
              <Input
                id={`inbound-fallback-${number.id}`}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                value={fallbackNumber}
                onChange={(event) => setFallbackNumber(event.target.value.trim())}
                placeholder={
                  readiness?.fallback_configured
                    ? "Configured; leave blank to keep"
                    : "+12025550123"
                }
                aria-describedby={`inbound-fallback-help-${number.id}`}
                aria-invalid={fallbackInvalid}
              />
              <p
                id={`inbound-fallback-help-${number.id}`}
                className={
                  fallbackInvalid ? "text-xs text-destructive" : "text-xs text-muted-foreground"
                }
                role={fallbackInvalid ? "alert" : undefined}
              >
                {fallbackInvalid
                  ? "Use E.164 format, such as +12025550123."
                  : "Used when AI or provider checks fail. Enter E.164 format."}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor={`inbound-transfer-${number.id}`}>Human transfer</Label>
              <Input
                id={`inbound-transfer-${number.id}`}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                value={transferNumber}
                onChange={(event) => setTransferNumber(event.target.value.trim())}
                placeholder={
                  readiness?.transfer_destination_configured
                    ? "Configured; leave blank to keep"
                    : "+12025550124"
                }
                aria-describedby={`inbound-transfer-help-${number.id}`}
                aria-invalid={transferInvalid}
              />
              <p
                id={`inbound-transfer-help-${number.id}`}
                className={
                  transferInvalid ? "text-xs text-destructive" : "text-xs text-muted-foreground"
                }
                role={transferInvalid ? "alert" : undefined}
              >
                {transferInvalid
                  ? "Use E.164 format, such as +12025550124."
                  : "Receives caller-requested warm transfers. Enter E.164 format."}
              </p>
            </div>
          </div>

          <div className="space-y-2 rounded-md border bg-muted/40 p-3">
            <p className="text-sm font-medium">Caller disclosure</p>
            <p className="text-sm text-muted-foreground">
              Before caller audio reaches OpenAI, the caller hears: “You are speaking with this
              business&apos;s AI assistant. This call will be transcribed to help with your request.
              By continuing, you agree to that processing.”
            </p>
            <p className="text-xs text-muted-foreground">
              Pilot calls are not raw-recorded. Legal review is still required for your calling
              jurisdictions.
            </p>
          </div>

          {!enabled && (
            <label className="flex gap-3 rounded-md border p-3 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 size-4 shrink-0"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              <span>
                I understand that enabling this number makes AI answer callers immediately after the
                disclosure.
              </span>
            </label>
          )}

          <div aria-live="polite" className="space-y-2">
            <p className="text-sm font-medium">Readiness checks</p>
            {readinessQuery.isPending && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                Checking configuration
              </p>
            )}
            {readinessQuery.isError && (
              <div className="flex items-center justify-between gap-3" role="alert">
                <p className="text-sm text-destructive">
                  Readiness could not be checked. Activation remains blocked.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => readinessQuery.refetch()}
                >
                  Retry
                </Button>
              </div>
            )}
            {displayedChecks && (
              <ul className="space-y-1.5">
                {displayedChecks.map((check) => (
                  <li key={check.code} className="flex items-start gap-2 text-sm">
                    {check.ready ? (
                      <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                    ) : (
                      <XCircle
                        className="mt-0.5 size-4 shrink-0 text-destructive"
                        aria-hidden="true"
                      />
                    )}
                    <span>
                      <span className="font-medium">{check.ready ? "Ready" : "Blocked"}:</span>{" "}
                      {check.message}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <div>
            {enabled && (
              <Button
                type="button"
                variant="outline"
                onClick={() => mutation.mutate({ enabled: false })}
                disabled={mutation.isPending}
              >
                Disable AI answering
              </Button>
            )}
          </div>
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={enable}
              disabled={!canEnable || mutation.isPending || readinessQuery.isError}
            >
              {mutation.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
              ) : (
                <PhoneForwarded className="mr-2 size-4" aria-hidden="true" />
              )}
              {enabled ? "Save AI settings" : "Enable AI answering"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
