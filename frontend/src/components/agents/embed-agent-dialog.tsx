"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Code2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { agentsApi, type EmbedSettingsUpdate } from "@/lib/api/agents";
import { queryKeys } from "@/lib/query-keys";

import { EmbedCodeBlock } from "./embed/embed-code-block";
import { EmbedConfigForm } from "./embed/embed-config-form";
import { EmbedPreviewLazy } from "./embed/embed-preview-lazy";
import type { EmbedFormValues } from "./embed/embed-types";

interface EmbedAgentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: string;
  agentName: string;
  workspaceId: string;
}

const DEFAULT_VALUES: EmbedFormValues = {
  embedEnabled: false,
  allowedDomains: [],
  buttonText: "Talk to AI",
  theme: "auto",
  position: "bottom-right",
  primaryColor: "#6366f1",
  mode: "voice",
  display: "floating",
};

const hasConfiguredDomain = (domains: string[] | undefined) =>
  domains?.some((domain) => domain.trim().length > 0) ?? false;

/**
 * Inner content for the embed-agent dialog. Owns the form state and routes
 * pieces of it into the extracted `EmbedConfigForm`, `EmbedCodeBlock`, and
 * (lazy) `EmbedPreviewLazy`.
 */
function EmbedDialogContent({
  onClose,
  agentId,
  agentName,
  workspaceId,
}: {
  onClose: () => void;
  agentId: string;
  agentName: string;
  workspaceId: string;
}) {
  const queryClient = useQueryClient();
  const [newDomain, setNewDomain] = useState("");
  const [localChanges, setLocalChanges] = useState<Partial<EmbedFormValues>>({});

  const { data: embedSettings, isPending } = useQuery({
    queryKey: queryKeys.agents.embed(workspaceId, agentId),
    queryFn: () => agentsApi.getEmbedSettings(workspaceId, agentId),
  });

  const values: EmbedFormValues = useMemo(() => {
    const base = embedSettings
      ? {
          embedEnabled: embedSettings.embed_enabled,
          allowedDomains: embedSettings.allowed_domains,
          buttonText: embedSettings.embed_settings.button_text,
          theme: embedSettings.embed_settings.theme,
          position: embedSettings.embed_settings.position,
          primaryColor: embedSettings.embed_settings.primary_color,
          mode: embedSettings.embed_settings.mode,
          display: embedSettings.embed_settings.display ?? "floating",
        }
      : DEFAULT_VALUES;

    return { ...base, ...localChanges };
  }, [embedSettings, localChanges]);

  const updateMutation = useMutation({
    mutationFn: (data: EmbedSettingsUpdate) =>
      agentsApi.updateEmbedSettings(workspaceId, agentId, data),
    onSuccess: (savedSettings) => {
      const queryKey = queryKeys.agents.embed(workspaceId, agentId);
      queryClient.setQueryData(queryKey, savedSettings);
      void queryClient.invalidateQueries({ queryKey });
      toast.success("Embed settings saved");
      setLocalChanges({});
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to save settings");
    },
  });

  const handleChange = (patch: Partial<EmbedFormValues>) => {
    setLocalChanges((prev) => ({ ...prev, ...patch }));
  };

  const handleSave = () => {
    updateMutation.mutate({
      embed_enabled: values.embedEnabled,
      allowed_domains: values.allowedDomains,
      embed_settings: {
        button_text: values.buttonText,
        theme: values.theme,
        position: values.position,
        primary_color: values.primaryColor,
        mode: values.mode,
        display: values.display,
      },
    });
  };

  const addDomain = () => {
    if (!newDomain.trim()) return;
    const domain = newDomain.trim().toLowerCase();
    if (!values.allowedDomains.includes(domain)) {
      handleChange({ allowedDomains: [...values.allowedDomains, domain] });
    }
    setNewDomain("");
  };

  const removeDomain = (domain: string) => {
    handleChange({
      allowedDomains: values.allowedDomains.filter((d) => d !== domain),
    });
  };

  const baseUrl = typeof window !== "undefined" ? window.location.origin : "";
  const publicId = embedSettings?.public_id || "";
  const savedEmbedEnabled = embedSettings?.embed_enabled === true;
  const hasSavedAllowedDomain = hasConfiguredDomain(embedSettings?.allowed_domains);
  const hasSavedPublicId = Boolean(publicId);
  const hasUnsavedAccessChanges =
    localChanges.embedEnabled !== undefined || localChanges.allowedDomains !== undefined;
  const canCopySnippets =
    savedEmbedEnabled && hasSavedAllowedDomain && hasSavedPublicId && !hasUnsavedAccessChanges;
  const embedCodeBlockedReason = !savedEmbedEnabled
    ? "Enable embedding and save this agent before copying the installation code."
    : !hasSavedAllowedDomain
      ? "Add the domain where this widget will run, or it will be blocked."
      : !hasSavedPublicId
        ? "Save embedding settings before copying the installation code."
        : hasUnsavedAccessChanges
          ? "Save your embedding and allowed-domain changes before copying the installation code."
          : "";

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Code2 className="h-5 w-5" />
          Embed {agentName}
        </DialogTitle>
        <DialogDescription>
          Add this AI agent to your website with a simple script tag or iframe.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-6">
        {/* Enable toggle */}
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div className="space-y-0.5">
            <Label htmlFor="agent-embed-enabled" className="text-base font-medium">
              Enable Embedding
            </Label>
            <p className="text-sm text-muted-foreground">
              Allow this agent to be embedded on external websites
            </p>
          </div>
          <Switch
            id="agent-embed-enabled"
            checked={values.embedEnabled}
            onCheckedChange={(v) => handleChange({ embedEnabled: v })}
          />
        </div>

        {values.embedEnabled && (
          <div className="flex flex-col gap-6 lg:flex-row">
            <div className="min-w-0 space-y-6 lg:w-[55%]">
              <EmbedConfigForm
                values={values}
                onChange={handleChange}
                newDomain={newDomain}
                onNewDomainChange={setNewDomain}
                onAddDomain={addDomain}
                onRemoveDomain={removeDomain}
              />

              <EmbedCodeBlock
                values={values}
                baseUrl={baseUrl}
                publicId={publicId}
                canCopySnippets={canCopySnippets}
                blockedReason={embedCodeBlockedReason}
              />
            </div>

            <EmbedPreviewLazy values={values} baseUrl={baseUrl} publicId={publicId} />
          </div>
        )}

        {/* Save button */}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={updateMutation.isPending}>
            {updateMutation.isPending ? "Saving..." : "Save Changes"}
          </Button>
        </div>
      </div>
    </>
  );
}

export function EmbedAgentDialog({
  open,
  onOpenChange,
  agentId,
  agentName,
  workspaceId,
}: EmbedAgentDialogProps) {
  // Use a key to reset state when dialog reopens.
  const [dialogKey, setDialogKey] = useState(0);

  const handleOpenChange = (newOpen: boolean) => {
    if (newOpen) {
      setDialogKey((k) => k + 1);
    }
    onOpenChange(newOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[900px]">
        {open ? (
          <EmbedDialogContent
            key={dialogKey}
            onClose={() => onOpenChange(false)}
            agentId={agentId}
            agentName={agentName}
            workspaceId={workspaceId}
          />
        ) : (
          <DialogTitle className="sr-only">Embed Agent</DialogTitle>
        )}
      </DialogContent>
    </Dialog>
  );
}
