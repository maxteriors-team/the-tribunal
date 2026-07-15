"use client";

import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ClipboardPaste,
  Copy,
  ExternalLink,
  Key,
  Loader2,
  Plug,
  Plus,
} from "lucide-react";
import { useCallback, useId, useState } from "react";
import { useFormContext } from "react-hook-form";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { verifyCalcom } from "@/lib/api/onboarding";
import { getApiErrorMessage } from "@/lib/utils/errors";

import type { OnboardingFormValues } from "../_state";

import { InstructionStep } from "./instruction-step";
import { useOnboardingExtras } from "./onboarding-context";

export function CalcomStep() {
  const form = useFormContext<OnboardingFormValues>();
  const { calcomConnected, calcomUsername, markCalcomConnected } =
    useOnboardingExtras();
  const apiKeyId = useId();
  const urlId = useId();
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);

  const { register, getValues, formState } = form;
  const apiKeyError = formState.errors.calcom_api_key?.message;
  const urlError = formState.errors.calcom_booking_url?.message;

  const handleTest = useCallback(async () => {
    const apiKey = getValues("calcom_api_key").trim();
    if (!apiKey) {
      toast.error("Paste your Cal.com API key first.");
      return;
    }
    setTesting(true);
    setTestError(null);
    try {
      const result = await verifyCalcom(apiKey);
      if (result.valid) {
        markCalcomConnected(result.username ?? null);
        toast.success(
          result.username
            ? `Connected as @${result.username}`
            : "Cal.com connection verified!"
        );
      } else {
        setTestError("Invalid API key. Please check and try again.");
      }
    } catch (err) {
      setTestError(getApiErrorMessage(err, "Connection test failed."));
    } finally {
      setTesting(false);
    }
  }, [getValues, markCalcomConnected]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Set Up Your Calendar</h2>
        <p className="text-muted-foreground mt-1">
          When a lead wants to meet, we&apos;ll book directly on your calendar
        </p>
      </div>

      <div className="space-y-3">
        <p className="text-sm font-medium text-muted-foreground">
          How to get your API key:
        </p>
        <div className="space-y-2">
          <InstructionStep
            icon={ExternalLink}
            title="Go to Cal.com"
            description="New to Cal.com? Sign up first. Already have an account? Go to API keys."
            link="https://cal.com/signup"
            linkLabel="Sign up for Cal.com"
          />
          <InstructionStep
            icon={ExternalLink}
            title="Already have an account?"
            link="https://app.cal.com/settings/developer/api-keys"
            linkLabel="Go to API keys"
          />
          <InstructionStep icon={Plus} title='Click "Create new key"' />
          <InstructionStep icon={Key} title="Copy the key" />
          <InstructionStep icon={ClipboardPaste} title="Paste it below" />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor={apiKeyId}>Cal.com API Key</Label>
        <div className="relative">
          <Key className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            id={apiKeyId}
            type="password"
            placeholder="cal_live_••••••••••••••••"
            className="pl-9"
            {...register("calcom_api_key")}
          />
        </div>
        {apiKeyError && (
          <p className="text-sm text-destructive">{apiKeyError}</p>
        )}
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

        {calcomConnected && (
          <Badge
            variant="outline"
            className="text-green-600 border-green-500 gap-1"
          >
            <CheckCircle2 className="size-3.5" />
            {calcomUsername ? `Connected as @${calcomUsername}` : "Connected"}
          </Badge>
        )}

        {testError && (
          <p className="text-sm text-destructive flex items-center gap-1">
            <AlertCircle className="size-3.5 shrink-0" />
            {testError}
          </p>
        )}
      </div>

      <div className="space-y-3">
        <p className="text-sm font-medium text-muted-foreground">
          How to get your booking URL:
        </p>
        <div className="space-y-2">
          <InstructionStep
            icon={ExternalLink}
            title="Go to Event Types"
            link="https://app.cal.com/event-types"
            linkLabel="Open Event Types"
          />
          <InstructionStep
            icon={Copy}
            title="Copy the URL of the event type you want leads to book"
            description="For example: https://cal.com/yourname/30min"
          />
          <InstructionStep icon={ClipboardPaste} title="Paste it below" />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor={urlId}>Cal.com Booking URL</Label>
        <div className="relative">
          <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            id={urlId}
            type="url"
            placeholder="https://cal.com/yourname/30min"
            className="pl-9"
            {...register("calcom_booking_url")}
          />
        </div>
        {urlError && <p className="text-sm text-destructive">{urlError}</p>}
      </div>
    </div>
  );
}
