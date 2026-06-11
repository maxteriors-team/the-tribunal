"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { useState, useEffect } from "react";
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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  integrationsApi,
  type CreateIntegrationRequest,
  type IntegrationWithMaskedCredentials,
} from "@/lib/api/integrations";
import { queryKeys } from "@/lib/query-keys";
type IntegrationType =
  | "calcom"
  | "telnyx"
  | "openai"
  | "resend"
  | "lob"
  | "followupboss";

interface IntegrationConfig {
  name: string;
  description: string;
  fields: {
    key: string;
    label: string;
    placeholder: string;
    description?: string;
    required?: boolean;
    type?: "text" | "password" | "email";
  }[];
}

const INTEGRATION_CONFIGS: Record<IntegrationType, IntegrationConfig> = {
  calcom: {
    name: "Cal.com",
    description: "Connect your Cal.com account for appointment scheduling",
    fields: [
      {
        key: "api_key",
        label: "API Key",
        placeholder: "cal_live_...",
        description: "Find this in Cal.com Settings > Developer > API Keys",
        required: true,
        type: "password",
      },
      {
        key: "event_type_id",
        label: "Event Type ID",
        placeholder: "123456",
        description: "Default event type for bookings (optional)",
      },
    ],
  },
  telnyx: {
    name: "Telnyx",
    description: "Connect Telnyx for voice calls and SMS messaging",
    fields: [
      {
        key: "api_key",
        label: "API Key",
        placeholder: "KEY...",
        description: "Find this in Telnyx Portal > API Keys",
        required: true,
        type: "password",
      },
      {
        key: "messaging_profile_id",
        label: "Messaging Profile ID",
        placeholder: "...",
        description: "Your Telnyx messaging profile ID",
      },
      {
        key: "phone_number",
        label: "Default Phone Number",
        placeholder: "+1234567890",
        description: "Default outbound phone number",
      },
    ],
  },
  openai: {
    name: "OpenAI API key",
    description: "Optional fallback API-key connection for OpenAI. Use the ChatGPT subscription card for Codex OAuth sign-in.",
    fields: [
      {
        key: "api_key",
        label: "API Key",
        placeholder: "sk-...",
        description: "Find this at platform.openai.com/api-keys. For subscription billing, use the ChatGPT subscription card instead.",
        type: "password",
      },
      {
        key: "access_token",
        label: "OAuth Access Token",
        placeholder: "eyJ...",
        description: "Advanced fallback only. Prefer the ChatGPT subscription card so tokens refresh automatically.",
        type: "password",
      },
      {
        key: "refresh_token",
        label: "OAuth Refresh Token",
        placeholder: "rt_...",
        description: "Advanced fallback only. Stored encrypted and refreshed automatically when possible.",
        type: "password",
      },
      {
        key: "expires_at",
        label: "OAuth Expires At",
        placeholder: "1780093083223",
        description: "Epoch milliseconds from auth.json (optional)",
      },
      {
        key: "account_id",
        label: "OpenAI Account ID",
        placeholder: "account uuid",
        description: "OpenAI accountId from auth.json (optional)",
      },
      {
        key: "organization_id",
        label: "Organization ID",
        placeholder: "org-...",
        description: "Your OpenAI organization ID (optional)",
      },
    ],
  },
  resend: {
    name: "Resend",
    description: "Connect Resend for email delivery and tracking",
    fields: [
      {
        key: "api_key",
        label: "API Key",
        placeholder: "re_...",
        description: "Find this in Resend Dashboard > API Keys",
        required: true,
        type: "password",
      },
      {
        key: "from_email",
        label: "From Email",
        placeholder: "noreply@example.com",
        description: "Default sender email address",
        type: "email",
      },
      {
        key: "from_name",
        label: "From Name",
        placeholder: "My Company",
        description: "Default sender display name",
      },
    ],
  },
  lob: {
    name: "Lob",
    description: "Send physical postcards and letters to contacts",
    fields: [
      {
        key: "api_key",
        label: "API Key",
        placeholder: "test_...",
        description: "Find in Lob Dashboard > Settings > API Keys",
        required: true,
        type: "password",
      },
    ],
  },
  followupboss: {
    name: "Follow Up Boss",
    description: "Sync leads from your Follow Up Boss CRM",
    fields: [
      {
        key: "api_key",
        label: "API Key",
        placeholder: "fub_api_...",
        description: "Find this in Follow Up Boss under Admin > API",
        required: true,
        type: "password",
      },
    ],
  },
};

// Dynamic schema based on integration type
function getSchema(integrationType: IntegrationType) {
  const config = INTEGRATION_CONFIGS[integrationType];
  const shape: Record<string, z.ZodTypeAny> = {};

  for (const field of config.fields) {
    if (field.required) {
      shape[field.key] = z.string().min(1, `${field.label} is required`);
    } else {
      shape[field.key] = z.string().optional();
    }
  }

  const schema = z.object(shape);

  if (integrationType === "openai") {
    return schema.refine(
      (values) => Boolean(values.api_key || values.access_token),
      {
        message: "Enter an API key or OAuth access token",
        path: ["api_key"],
      }
    );
  }

  return schema;
}

interface IntegrationConfigDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  integrationType: IntegrationType;
  existingIntegration?: IntegrationWithMaskedCredentials | null;
}

export function IntegrationConfigDialog({
  open,
  onOpenChange,
  integrationType,
  existingIntegration,
}: IntegrationConfigDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  const config = INTEGRATION_CONFIGS[integrationType];
  const schema = getSchema(integrationType);
  type FormValues = z.infer<typeof schema>;

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: config.fields.reduce(
      (acc, field) => {
        acc[field.key] = "";
        return acc;
      },
      {} as Record<string, string>
    ),
  });

  // Reset form when dialog opens/closes or integration changes
  useEffect(() => {
    if (open) {
      form.reset(
        config.fields.reduce(
          (acc, field) => {
            acc[field.key] = "";
            return acc;
          },
          {} as Record<string, string>
        )
      );
    }
  }, [open, integrationType, form, config.fields]);

  // Derive effective test result - null when dialog is closed
  const effectiveTestResult = open ? testResult : null;

  const createMutation = useMutation({
    mutationFn: (data: CreateIntegrationRequest) =>
      integrationsApi.create(workspaceId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.integrations(workspaceId ?? ""),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.integrations.all(workspaceId ?? ""),
      });
      toast.success(`${config.name} connected successfully!`);
      onOpenChange(false);
    },
    onError: (error: Error) => {
      const axiosError = error as AxiosError<{ detail?: string }>;
      const message = axiosError.response?.data?.detail || `Failed to connect ${config.name}`;
      toast.error(message);
    },
    onSettled: () => {
      setIsSubmitting(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (credentials: Record<string, string>) =>
      integrationsApi.update(workspaceId!, integrationType, { credentials }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.integrations(workspaceId ?? ""),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.integrations.all(workspaceId ?? ""),
      });
      toast.success(`${config.name} updated successfully!`);
      onOpenChange(false);
    },
    onError: (error: Error) => {
      const axiosError = error as AxiosError<{ detail?: string }>;
      const message = axiosError.response?.data?.detail || `Failed to update ${config.name}`;
      toast.error(message);
    },
    onSettled: () => {
      setIsSubmitting(false);
    },
  });

  const testMutation = useMutation({
    mutationFn: () => integrationsApi.test(workspaceId!, integrationType),
    onSuccess: (result) => {
      setTestResult(result);
    },
    onError: () => {
      setTestResult({ success: false, message: "Failed to test connection" });
    },
    onSettled: () => {
      setIsTesting(false);
    },
  });

  const handleSubmit = (data: FormValues) => {
    if (isSubmitting) return;

    if (!workspaceId) {
      toast.error("No workspace selected. Please select a workspace first.");
      return;
    }

    setIsSubmitting(true);

    // Filter out empty optional fields
    const credentials: Record<string, string> = {};
    for (const [key, value] of Object.entries(data)) {
      if (value) {
        credentials[key] = value as string;
      }
    }

    if (existingIntegration) {
      updateMutation.mutate(credentials);
    } else {
      createMutation.mutate({
        integration_type: integrationType as CreateIntegrationRequest["integration_type"],
        credentials,
      });
    }
  };

  const handleTest = () => {
    if (!existingIntegration || isTesting) return;
    setIsTesting(true);
    setTestResult(null);
    testMutation.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {existingIntegration ? "Configure" : "Connect"} {config.name}
          </DialogTitle>
          <DialogDescription>{config.description}</DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            {config.fields.map((field) => (
              <FormField
                key={field.key}
                control={form.control}
                name={field.key}
                render={({ field: formField }) => (
                  <FormItem>
                    <FormLabel>
                      {field.label}
                      {field.required && " *"}
                    </FormLabel>
                    <FormControl>
                      <Input
                        type={field.type || "text"}
                        placeholder={field.placeholder}
                        name={formField.name}
                        ref={formField.ref}
                        onBlur={formField.onBlur}
                        onChange={formField.onChange}
                        value={(formField.value as string) ?? ""}
                      />
                    </FormControl>
                    {field.description && (
                      <FormDescription>{field.description}</FormDescription>
                    )}
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}

            {existingIntegration && (
              <div className="rounded-lg border p-3 bg-muted/50">
                <p className="text-sm text-muted-foreground mb-2">
                  Current credentials are stored. Enter new values to update.
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleTest}
                    disabled={isTesting}
                  >
                    {isTesting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Test Connection
                  </Button>
                  {effectiveTestResult && (
                    <div className="flex items-center gap-1 text-sm">
                      {effectiveTestResult.success ? (
                        <>
                          <CheckCircle2 className="h-4 w-4 text-success" />
                          <span className="text-success">{effectiveTestResult.message}</span>
                        </>
                      ) : (
                        <>
                          <XCircle className="h-4 w-4 text-destructive" />
                          <span className="text-destructive">{effectiveTestResult.message}</span>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isSubmitting
                  ? "Saving..."
                  : existingIntegration
                    ? "Update"
                    : "Connect"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
