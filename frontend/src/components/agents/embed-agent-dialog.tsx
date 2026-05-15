"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Copy, Check, ExternalLink, Plus, X, Code2, Link2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { agentsApi, type EmbedSettingsUpdate } from "@/lib/api/agents";
import { queryKeys } from "@/lib/query-keys";

interface EmbedAgentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: string;
  agentName: string;
  workspaceId: string;
}

const POSITION_OPTIONS = [
  { value: "bottom-right", label: "Bottom Right" },
  { value: "bottom-left", label: "Bottom Left" },
  { value: "top-right", label: "Top Right" },
  { value: "top-left", label: "Top Left" },
];

const THEME_OPTIONS = [
  { value: "auto", label: "Auto (System)" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const MODE_OPTIONS = [
  { value: "voice", label: "Voice Only" },
  { value: "chat", label: "Chat Only" },
  { value: "both", label: "Both" },
];

const DISPLAY_OPTIONS = [
  { value: "floating", label: "Floating Widget" },
  { value: "inline", label: "Inline Embed" },
  { value: "fullpage", label: "Full Page" },
];

// Simple QR code component using canvas
function QRCode({ value }: { value: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !value) return;

    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      canvas.width = 128;
      canvas.height = 128;
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, 128, 128);
      ctx.drawImage(img, 0, 0, 128, 128);
    };
    img.src = `https://api.qrserver.com/v1/create-qr-code/?size=128x128&data=${encodeURIComponent(value)}`;
  }, [value]);

  return (
    <div className="flex items-center gap-3">
      <canvas
        ref={canvasRef}
        width={128}
        height={128}
        className="rounded-lg border"
        style={{ width: 96, height: 96 }}
      />
      <p className="text-xs text-muted-foreground">
        Scan to open the agent on any device
      </p>
    </div>
  );
}

// Inner component that manages its own form state
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
  const [copiedTab, setCopiedTab] = useState<string | null>(null);
  const [newDomain, setNewDomain] = useState("");

  // Fetch embed settings
  const { data: embedSettings, isPending } = useQuery({
    queryKey: queryKeys.agents.embed(workspaceId, agentId),
    queryFn: () => agentsApi.getEmbedSettings(workspaceId, agentId),
  });

  // Form state - track local changes from the base data
  const [localChanges, setLocalChanges] = useState<{
    embedEnabled?: boolean;
    allowedDomains?: string[];
    buttonText?: string;
    theme?: string;
    position?: string;
    primaryColor?: string;
    mode?: string;
    display?: string;
  }>({});

  // Compute current values (base from server + local changes)
  const currentValues = useMemo(() => {
    const base = embedSettings ?? {
      embed_enabled: false,
      allowed_domains: [],
      embed_settings: {
        button_text: "Talk to AI",
        theme: "auto",
        position: "bottom-right",
        primary_color: "#6366f1",
        mode: "voice",
        display: "floating",
      },
    };

    return {
      embedEnabled: localChanges.embedEnabled ?? base.embed_enabled,
      allowedDomains: localChanges.allowedDomains ?? base.allowed_domains,
      buttonText: localChanges.buttonText ?? base.embed_settings.button_text,
      theme: localChanges.theme ?? base.embed_settings.theme,
      position: localChanges.position ?? base.embed_settings.position,
      primaryColor: localChanges.primaryColor ?? base.embed_settings.primary_color,
      mode: localChanges.mode ?? base.embed_settings.mode,
      display: localChanges.display ?? base.embed_settings.display ?? "floating",
    };
  }, [embedSettings, localChanges]);

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: (data: EmbedSettingsUpdate) =>
      agentsApi.updateEmbedSettings(workspaceId, agentId, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agents.embed(workspaceId, agentId),
      });
      toast.success("Embed settings saved");
      setLocalChanges({});
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to save settings");
    },
  });

  const handleSave = () => {
    updateMutation.mutate({
      embed_enabled: currentValues.embedEnabled,
      allowed_domains: currentValues.allowedDomains,
      embed_settings: {
        button_text: currentValues.buttonText,
        theme: currentValues.theme,
        position: currentValues.position,
        primary_color: currentValues.primaryColor,
        mode: currentValues.mode,
        display: currentValues.display,
      },
    });
  };

  const addDomain = () => {
    if (!newDomain.trim()) return;
    const domain = newDomain.trim().toLowerCase();
    if (!currentValues.allowedDomains.includes(domain)) {
      setLocalChanges({
        ...localChanges,
        allowedDomains: [...currentValues.allowedDomains, domain],
      });
    }
    setNewDomain("");
  };

  const removeDomain = (domain: string) => {
    setLocalChanges({
      ...localChanges,
      allowedDomains: currentValues.allowedDomains.filter((d) => d !== domain),
    });
  };

  const copyToClipboard = (text: string, tabId: string) => {
    void navigator.clipboard.writeText(text);
    setCopiedTab(tabId);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopiedTab(null), 2000);
  };

  // Generate embed URLs and code snippets
  const baseUrl = typeof window !== "undefined" ? window.location.origin : "";
  const publicId = embedSettings?.public_id || "";

  const modePath = useMemo(() => {
    if (currentValues.display === "fullpage") return "fullpage";
    if (currentValues.mode === "chat") return "chat";
    if (currentValues.mode === "both") return "both";
    return "";
  }, [currentValues.display, currentValues.mode]);

  const previewUrl = useMemo(() => {
    const path = modePath ? `/embed/${publicId}/${modePath}` : `/embed/${publicId}`;
    return `${path}?theme=${currentValues.theme}&preview=true`;
  }, [publicId, modePath, currentValues.theme]);

  // Memoized code snippets
  const loaderSnippet = useMemo(
    () =>
      `<script src="${baseUrl}/widget/v1/loader.js" data-agent-id="${publicId}" defer></script>`,
    [baseUrl, publicId]
  );

  const scriptCode = useMemo(() => {
    const displayAttr =
      currentValues.display !== "floating" ? ` display="${currentValues.display}"` : "";
    return `<script src="${baseUrl}/widget/v1/widget.js" defer></script>\n<ai-agent agent-id="${publicId}" mode="${currentValues.mode}"${displayAttr}></ai-agent>`;
  }, [baseUrl, publicId, currentValues.mode, currentValues.display]);

  const reactCode = useMemo(() => {
    const iframeModePath = modePath ? `/${modePath}` : "";
    return `export function AIAgent() {
  return (
    <iframe
      src="${baseUrl}/embed/${publicId}${iframeModePath}?theme=${currentValues.theme}"
      width="100%"
      height="600"
      allow="microphone"
      style={{ border: 'none', borderRadius: '16px' }}
    />
  );
}`;
  }, [baseUrl, publicId, modePath, currentValues.theme]);

  const iframeCode = useMemo(() => {
    const iframeModePath = modePath ? `/${modePath}` : "";
    const isFullpage = currentValues.display === "fullpage";
    const width = isFullpage ? "100%" : "400";
    const height = isFullpage ? "100%" : "600";
    return `<iframe
  src="${baseUrl}/embed/${publicId}${iframeModePath}?theme=${currentValues.theme}"
  width="${width}"
  height="${height}"
  allow="microphone"
  style="border: none; border-radius: 16px;"
></iframe>`;
  }, [baseUrl, publicId, modePath, currentValues.theme, currentValues.display]);

  // Key for preview iframe reloading
  const previewKey = `${currentValues.theme}-${currentValues.mode}-${currentValues.primaryColor}-${currentValues.display}`;

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const renderCopyButton = (code: string, tabId: string) => (
    <Button
      size="icon"
      variant="ghost"
      className="absolute right-2 top-2 h-8 w-8"
      onClick={() => copyToClipboard(code, tabId)}
      aria-label="Copy code"
    >
      {copiedTab === tabId ? (
        <Check className="h-4 w-4 text-success" />
      ) : (
        <Copy className="h-4 w-4" />
      )}
    </Button>
  );

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
            <Label className="text-base font-medium">Enable Embedding</Label>
            <p className="text-sm text-muted-foreground">
              Allow this agent to be embedded on external websites
            </p>
          </div>
          <Switch
            checked={currentValues.embedEnabled}
            onCheckedChange={(v) => setLocalChanges({ ...localChanges, embedEnabled: v })}
          />
        </div>

        {currentValues.embedEnabled && (
          <div className="flex flex-col gap-6 lg:flex-row">
            {/* Left column: settings + code */}
            <div className="min-w-0 space-y-6 lg:w-[55%]">
              {/* Domain allowlist */}
              <div className="space-y-3">
                <Label>Allowed Domains</Label>
                <p className="text-xs text-muted-foreground">
                  Specify which domains can embed this agent. Use *.example.com for subdomains.
                </p>
                <div className="flex gap-2">
                  <Input
                    placeholder="example.com"
                    value={newDomain}
                    onChange={(e) => setNewDomain(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addDomain()}
                  />
                  <Button type="button" variant="outline" size="icon" onClick={addDomain} aria-label="Add domain">
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
                {currentValues.allowedDomains.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {currentValues.allowedDomains.map((domain) => (
                      <Badge key={domain} variant="secondary" className="gap-1">
                        {domain}
                        <button
                          type="button"
                          onClick={() => removeDomain(domain)}
                          className="ml-1 rounded-full hover:bg-destructive/20"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              {/* Settings */}
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Mode</Label>
                  <Select
                    value={currentValues.mode}
                    onValueChange={(v) => setLocalChanges({ ...localChanges, mode: v })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MODE_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Display</Label>
                  <Select
                    value={currentValues.display}
                    onValueChange={(v) => setLocalChanges({ ...localChanges, display: v })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {DISPLAY_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Position</Label>
                  <Select
                    value={currentValues.position}
                    onValueChange={(v) => setLocalChanges({ ...localChanges, position: v })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {POSITION_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Theme</Label>
                  <Select
                    value={currentValues.theme}
                    onValueChange={(v) => setLocalChanges({ ...localChanges, theme: v })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {THEME_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Primary Color</Label>
                  <div className="flex gap-2">
                    <Input
                      type="color"
                      value={currentValues.primaryColor}
                      onChange={(e) =>
                        setLocalChanges({ ...localChanges, primaryColor: e.target.value })
                      }
                      className="h-10 w-14 cursor-pointer p-1"
                    />
                    <Input
                      value={currentValues.primaryColor}
                      onChange={(e) =>
                        setLocalChanges({ ...localChanges, primaryColor: e.target.value })
                      }
                      className="font-mono"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Button Text</Label>
                  <Input
                    value={currentValues.buttonText}
                    onChange={(e) =>
                      setLocalChanges({ ...localChanges, buttonText: e.target.value })
                    }
                    placeholder="Talk to AI"
                  />
                </div>
              </div>

              {/* Embed code tabs */}
              <Tabs defaultValue="quickstart" className="w-full">
                <TabsList className="flex w-full overflow-x-auto">
                  <TabsTrigger value="quickstart" className="text-xs">Quick Start</TabsTrigger>
                  <TabsTrigger value="htmljs" className="text-xs">HTML / JS</TabsTrigger>
                  <TabsTrigger value="react" className="text-xs">React</TabsTrigger>
                  <TabsTrigger value="wordpress" className="text-xs">WordPress</TabsTrigger>
                  <TabsTrigger value="shopify" className="text-xs">Shopify</TabsTrigger>
                  <TabsTrigger value="webflow" className="text-xs">Webflow</TabsTrigger>
                  <TabsTrigger value="iframe" className="text-xs">iframe</TabsTrigger>
                </TabsList>

                {/* Quick Start */}
                <TabsContent value="quickstart" className="space-y-2">
                  <div className="relative">
                    <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
                      {loaderSnippet}
                    </pre>
                    {renderCopyButton(loaderSnippet, "quickstart")}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Add this single line before {`</body>`}. That&apos;s it — settings are
                    auto-loaded.
                  </p>
                </TabsContent>

                {/* HTML / JS */}
                <TabsContent value="htmljs" className="space-y-2">
                  <div className="relative">
                    <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
                      {scriptCode}
                    </pre>
                    {renderCopyButton(scriptCode, "htmljs")}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Add this code before the closing {`</body>`} tag of your website.
                  </p>
                </TabsContent>

                {/* React */}
                <TabsContent value="react" className="space-y-2">
                  <div className="relative">
                    <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
                      {reactCode}
                    </pre>
                    {renderCopyButton(reactCode, "react")}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Drop this component anywhere in your React app.
                  </p>
                </TabsContent>

                {/* WordPress */}
                <TabsContent value="wordpress" className="space-y-2">
                  <p className="text-xs text-muted-foreground">
                    Go to <strong>Appearance → Widgets → Custom HTML</strong> (or your
                    theme&apos;s footer). Paste this code:
                  </p>
                  <div className="relative">
                    <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
                      {loaderSnippet}
                    </pre>
                    {renderCopyButton(loaderSnippet, "wordpress")}
                  </div>
                </TabsContent>

                {/* Shopify */}
                <TabsContent value="shopify" className="space-y-2">
                  <p className="text-xs text-muted-foreground">
                    Go to <strong>Online Store → Themes → Edit Code → theme.liquid</strong>.
                    Paste before {`</body>`}:
                  </p>
                  <div className="relative">
                    <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
                      {loaderSnippet}
                    </pre>
                    {renderCopyButton(loaderSnippet, "shopify")}
                  </div>
                </TabsContent>

                {/* Webflow */}
                <TabsContent value="webflow" className="space-y-2">
                  <p className="text-xs text-muted-foreground">
                    Go to <strong>Project Settings → Custom Code → Footer Code</strong>. Paste:
                  </p>
                  <div className="relative">
                    <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
                      {loaderSnippet}
                    </pre>
                    {renderCopyButton(loaderSnippet, "webflow")}
                  </div>
                </TabsContent>

                {/* iframe */}
                <TabsContent value="iframe" className="space-y-2">
                  <div className="relative">
                    <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
                      {iframeCode}
                    </pre>
                    {renderCopyButton(iframeCode, "iframe")}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Use this iframe to embed the agent directly on your page.
                  </p>
                </TabsContent>
              </Tabs>

              {/* Share Link */}
              {publicId && (
                <div className="space-y-3 rounded-lg border p-4">
                  <div className="flex items-center gap-2">
                    <Link2 className="h-4 w-4 text-muted-foreground" />
                    <Label className="text-sm font-medium">Share Link</Label>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Share this direct link — no embedding required.
                  </p>
                  <div className="flex items-center gap-2">
                    <Input
                      readOnly
                      value={`${baseUrl}/embed/${publicId}/fullpage?theme=${currentValues.theme}`}
                      className="flex-1 font-mono text-xs"
                    />
                    <Button
                      size="icon"
                      variant="outline"
                      onClick={() =>
                        copyToClipboard(
                          `${baseUrl}/embed/${publicId}/fullpage?theme=${currentValues.theme}`,
                          "sharelink"
                        )
                      }
                      aria-label="Copy share link"
                    >
                      {copiedTab === "sharelink" ? (
                        <Check className="h-4 w-4 text-success" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                    </Button>
                    <Button size="icon" variant="outline" asChild>
                      <a
                        href={`${baseUrl}/embed/${publicId}/fullpage?theme=${currentValues.theme}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="Open share link in new tab"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </a>
                    </Button>
                  </div>
                  <QRCode
                    value={`${baseUrl}/embed/${publicId}/fullpage?theme=${currentValues.theme}`}
                  />
                </div>
              )}
            </div>

            {/* Right column: live preview */}
            <div className="min-w-0 space-y-2 lg:w-[45%]">
              <Label className="text-sm font-medium text-muted-foreground">Live Preview</Label>
              {publicId ? (
                <div className="overflow-hidden rounded-xl border">
                  <iframe
                    key={previewKey}
                    src={`${baseUrl}${previewUrl}`}
                    width="100%"
                    height="400px"
                    className="block rounded-xl"
                    style={{ border: "none" }}
                    allow="microphone"
                    title="Embed preview"
                  />
                </div>
              ) : (
                <div className="flex h-[400px] items-center justify-center rounded-xl border bg-muted text-sm text-muted-foreground">
                  Save settings to generate a preview
                </div>
              )}
            </div>
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
  // Use key to reset state when dialog opens
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
