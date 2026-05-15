"use client";

import { useCallback, useId, useState } from "react";
import { useFormContext } from "react-hook-form";
import { toast } from "sonner";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardPaste,
  ExternalLink,
  Key,
  Loader2,
  Plug,
  Settings,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { verifyFub } from "@/lib/api/realtor";
import { getApiErrorMessage } from "@/lib/utils/errors";

import type { OnboardingFormValues } from "../_state";
import { InstructionStep } from "./instruction-step";
import { useOnboardingExtras } from "./onboarding-context";

export function FubStep() {
  const form = useFormContext<OnboardingFormValues>();
  const { fubConnected, fubName, markFubConnected } = useOnboardingExtras();
  const apiKeyId = useId();
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);

  const { register, getValues } = form;
  const error = form.formState.errors.fub_api_key?.message;

  const handleTest = useCallback(async () => {
    const apiKey = getValues("fub_api_key").trim();
    if (!apiKey) {
      toast.error("Paste your Follow Up Boss API key first.");
      return;
    }
    setTesting(true);
    setTestError(null);
    try {
      const result = await verifyFub(apiKey);
      if (result.valid) {
        markFubConnected(result.name ?? null);
        toast.success(
          result.name
            ? `Connected as ${result.name}`
            : "Follow Up Boss connected!"
        );
      } else {
        setTestError("That API key didn't work. Double-check and try again.");
      }
    } catch (err) {
      setTestError(getApiErrorMessage(err, "Connection test failed."));
    } finally {
      setTesting(false);
    }
  }, [getValues, markFubConnected]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Connect Your CRM</h2>
        <p className="text-muted-foreground mt-1">
          We&apos;ll pull your leads directly from Follow Up Boss
        </p>
      </div>

      <div className="space-y-3">
        <p className="text-sm font-medium text-muted-foreground">
          How to find your API key:
        </p>
        <div className="space-y-2">
          <InstructionStep
            icon={ExternalLink}
            title="Log into Follow Up Boss"
            link="https://app.followupboss.com"
            linkLabel="Open Follow Up Boss"
          />
          <InstructionStep
            icon={Settings}
            title="Click Admin in the top menu, then click API"
          />
          <InstructionStep icon={Key} title="Copy your API key" />
          <InstructionStep icon={ClipboardPaste} title="Paste it below" />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor={apiKeyId}>Follow Up Boss API Key</Label>
        <div className="relative">
          <Key className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            id={apiKeyId}
            type="password"
            placeholder="fub_api_••••••••••••••••"
            className="pl-9"
            {...register("fub_api_key")}
          />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>

      <div className="flex items-center gap-3">
        <Button
          type="button"
          variant="outline"
          onClick={handleTest}
          disabled={testing}
        >
          {testing ? (
            <Loader2 className="size-4 mr-2 animate-spin" />
          ) : (
            <Plug className="size-4 mr-2" />
          )}
          Test Connection
        </Button>

        {fubConnected && (
          <Badge
            variant="outline"
            className="text-green-600 border-green-500 gap-1"
          >
            <CheckCircle2 className="size-3.5" />
            {fubName ? `Connected as ${fubName}` : "Connected"}
          </Badge>
        )}

        {testError && (
          <p className="text-sm text-destructive flex items-center gap-1">
            <AlertCircle className="size-3.5 shrink-0" />
            {testError}
          </p>
        )}
      </div>
    </div>
  );
}
