"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Copy,
  Trash2,
  Pencil,
  Loader2,
  Check,
  Globe,
  X,
} from "lucide-react";
import { useState } from "react";

import {
  SourceTypePicker,
  sourceTypeLabel,
} from "@/components/lead-sources/source-pickers";
import { OutboundAutopilotCard } from "@/components/settings/outbound-autopilot-card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import { Switch } from "@/components/ui/switch";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { agentsApi } from "@/lib/api/agents";
import { campaignsApi } from "@/lib/api/campaigns";
import {
  leadSourcesApi,
  type LeadSource,
  type LeadSourceCreateRequest,
  type LeadSourceType,
  type LeadSourceUpdateRequest,
} from "@/lib/api/lead-sources";
import { queryKeys } from "@/lib/query-keys";
import type { Campaign } from "@/types";
import type { Agent } from "@/types/agent";

const ACTION_LABELS: Record<string, string> = {
  collect: "Collect Only",
  auto_text: "Auto Text",
  auto_call: "Auto Call",
  enroll_campaign: "Enroll in Campaign",
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-7"
      onClick={handleCopy}
      aria-label={copied ? "Copied" : "Copy to clipboard"}
    >
      {copied ? (
        <Check className="size-3.5 text-green-500" />
      ) : (
        <Copy className="size-3.5" />
      )}
    </Button>
  );
}

interface LeadSourceFormData {
  name: string;
  allowed_domains: string[];
  source_type: LeadSourceType;
  action: "collect" | "auto_text" | "auto_call" | "enroll_campaign";
  action_config: Record<string, string>;
  enabled: boolean;
}

function LeadSourceDialog({
  open,
  onOpenChange,
  source,
  workspaceId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  source: LeadSource | null;
  workspaceId: string;
}) {
  const queryClient = useQueryClient();
  const isEditing = !!source;

  const [form, setForm] = useState<LeadSourceFormData>(() =>
    source
      ? {
          name: source.name,
          allowed_domains: source.allowed_domains,
          source_type: source.source_type,
          action: source.action,
          action_config: source.action_config,
          enabled: source.enabled,
        }
      : {
          name: "",
          allowed_domains: [],
          source_type: "other",
          action: "collect",
          action_config: {},
          enabled: true,
        }
  );
  const [domainInput, setDomainInput] = useState("");

  // Load agents and campaigns for action config
  const { data: agentsData } = useQuery({
    queryKey: queryKeys.agents.all(workspaceId ?? ""),
    queryFn: () => agentsApi.list(workspaceId),
    enabled: form.action === "auto_text" || form.action === "auto_call",
  });

  const { data: campaignsData } = useQuery({
    queryKey: queryKeys.campaigns.all(workspaceId ?? ""),
    queryFn: () => campaignsApi.list(workspaceId),
    enabled: form.action === "enroll_campaign",
  });

  const agents: Agent[] = agentsData?.items ?? [];
  const campaigns: Campaign[] = campaignsData?.items ?? [];

  const createMutation = useMutation({
    mutationFn: (data: LeadSourceCreateRequest) =>
      leadSourcesApi.create(workspaceId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.leadSources.all(workspaceId ?? "") });
      onOpenChange(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: LeadSourceUpdateRequest) =>
      leadSourcesApi.update(workspaceId, source!.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.leadSources.all(workspaceId ?? "") });
      onOpenChange(false);
    },
  });

  const handleAddDomain = () => {
    const domain = domainInput.trim().toLowerCase();
    if (domain && !form.allowed_domains.includes(domain)) {
      setForm((f) => ({
        ...f,
        allowed_domains: [...f.allowed_domains, domain],
      }));
      setDomainInput("");
    }
  };

  const handleRemoveDomain = (domain: string) => {
    setForm((f) => ({
      ...f,
      allowed_domains: f.allowed_domains.filter((d) => d !== domain),
    }));
  };

  const handleSubmit = () => {
    if (isEditing) {
      updateMutation.mutate({
        name: form.name,
        allowed_domains: form.allowed_domains,
        source_type: form.source_type,
        action: form.action,
        action_config: form.action_config,
        enabled: form.enabled,
      });
    } else {
      createMutation.mutate({
        name: form.name,
        allowed_domains: form.allowed_domains,
        source_type: form.source_type,
        action: form.action,
        action_config: form.action_config,
      });
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Lead Source" : "Create Lead Source"}
          </DialogTitle>
          <DialogDescription>
            Configure where leads come from and what happens after capture.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              placeholder="e.g. Pricing Page Leads"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>

          {/* Channel (source_type) */}
          <div className="space-y-2">
            <Label htmlFor="source-channel">Channel</Label>
            <SourceTypePicker
              id="source-channel"
              value={form.source_type}
              onChange={(v) => setForm((f) => ({ ...f, source_type: v }))}
            />
            <p className="text-xs text-muted-foreground">
              Used to rank lead-source ROI by acquisition channel.
            </p>
          </div>

          {/* Allowed Domains */}
          <div className="space-y-2">
            <Label>Allowed Domains</Label>
            <div className="flex gap-2">
              <Input
                placeholder="example.com or *.example.com"
                value={domainInput}
                onChange={(e) => setDomainInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAddDomain();
                  }
                }}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleAddDomain}
              >
                Add
              </Button>
            </div>
            {form.allowed_domains.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {form.allowed_domains.map((domain) => (
                  <Badge key={domain} variant="secondary" className="gap-1">
                    {domain}
                    <button
                      type="button"
                      onClick={() => handleRemoveDomain(domain)}
                      className="ml-0.5 hover:text-destructive"
                    >
                      <X className="size-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              Domains that are allowed to submit leads. Supports wildcards
              (*.example.com).
            </p>
          </div>

          {/* Action */}
          <div className="space-y-2">
            <Label>Post-Capture Action</Label>
            <Select
              value={form.action}
              onValueChange={(v) =>
                setForm((f) => ({
                  ...f,
                  action: v as LeadSourceFormData["action"],
                  action_config: {},
                }))
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="collect">Collect Only</SelectItem>
                <SelectItem value="auto_text">Auto Text</SelectItem>
                <SelectItem value="auto_call">Auto Call</SelectItem>
                <SelectItem value="enroll_campaign">
                  Enroll in Campaign
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Action Config - Agent + Phone (auto_text, auto_call) */}
          {(form.action === "auto_text" || form.action === "auto_call") && (
            <>
              <div className="space-y-2">
                <Label>Agent</Label>
                <Select
                  value={form.action_config.agent_id ?? ""}
                  onValueChange={(v) =>
                    setForm((f) => ({
                      ...f,
                      action_config: { ...f.action_config, agent_id: v },
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select an agent" />
                  </SelectTrigger>
                  <SelectContent>
                    {agents.map((agent) => (
                      <SelectItem key={agent.id} value={agent.id}>
                        {agent.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>From Phone Number</Label>
                <Input
                  placeholder="+1234567890"
                  value={form.action_config.from_phone_number ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      action_config: {
                        ...f.action_config,
                        from_phone_number: e.target.value,
                      },
                    }))
                  }
                />
              </div>
            </>
          )}

          {/* Action Config - Message Template (auto_text only) */}
          {form.action === "auto_text" && (
            <div className="space-y-2">
              <Label>Message Template (optional)</Label>
              <Input
                placeholder="Hi {name}! Thanks for your interest..."
                value={form.action_config.message_template ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    action_config: {
                      ...f.action_config,
                      message_template: e.target.value,
                    },
                  }))
                }
              />
              <p className="text-xs text-muted-foreground">
                Leave blank for default message.
              </p>
            </div>
          )}

          {/* Action Config - Campaign (enroll_campaign) */}
          {form.action === "enroll_campaign" && (
            <div className="space-y-2">
              <Label>Campaign</Label>
              <Select
                value={form.action_config.campaign_id ?? ""}
                onValueChange={(v) =>
                  setForm((f) => ({
                    ...f,
                    action_config: { ...f.action_config, campaign_id: v },
                  }))
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a campaign" />
                </SelectTrigger>
                <SelectContent>
                  {campaigns.map((campaign) => (
                    <SelectItem key={campaign.id} value={campaign.id}>
                      {campaign.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Enabled toggle (edit only) */}
          {isEditing && (
            <div className="flex items-center justify-between">
              <Label>Enabled</Label>
              <Switch
                checked={form.enabled}
                onCheckedChange={(checked) =>
                  setForm((f) => ({ ...f, enabled: checked }))
                }
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!form.name.trim() || isPending}
          >
            {isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            {isEditing ? "Save Changes" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function LeadSourcesSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSource, setEditingSource] = useState<LeadSource | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LeadSource | null>(null);

  const { data: sources, isPending } = useQuery({
    queryKey: queryKeys.leadSources.all(workspaceId ?? ""),
    queryFn: () => leadSourcesApi.list(workspaceId!),
    enabled: !!workspaceId,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => leadSourcesApi.delete(workspaceId!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.leadSources.all(workspaceId ?? "") });
      setDeleteTarget(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      leadSourcesApi.update(workspaceId!, id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.leadSources.all(workspaceId ?? "") });
    },
  });

  const handleCreate = () => {
    setEditingSource(null);
    setDialogOpen(true);
  };

  const handleEdit = (source: LeadSource) => {
    setEditingSource(source);
    setDialogOpen(true);
  };

  return (
    <div className="space-y-6">
      {workspaceId && <OutboundAutopilotCard workspaceId={workspaceId} />}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Lead Sources</CardTitle>
              <CardDescription>
                Configure public endpoints to capture leads from external
                websites. Each source has its own allowed domains and
                post-capture action.
              </CardDescription>
            </div>
            <Button onClick={handleCreate}>
              <Plus className="mr-2 size-4" />
              Add Source
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isPending ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : !sources?.length ? (
            <div className="text-center py-12 text-muted-foreground">
              <Globe className="mx-auto size-10 mb-3 opacity-50" />
              <p className="font-medium">No lead sources yet</p>
              <p className="text-sm mt-1">
                Create a lead source to start capturing leads from your
                websites.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {sources.map((source) => (
                <div
                  key={source.id}
                  className="flex items-start justify-between gap-4 rounded-lg border p-4"
                >
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <h4 className="font-medium">{source.name}</h4>
                      <Badge
                        variant={source.enabled ? "default" : "secondary"}
                        className="text-xs"
                      >
                        {source.enabled ? "Active" : "Disabled"}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {sourceTypeLabel(source.source_type)}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {ACTION_LABELS[source.action] ?? source.action}
                      </Badge>
                    </div>

                    {/* Endpoint URL */}
                    <div className="flex items-center gap-1">
                      <code className="text-xs text-muted-foreground font-mono truncate">
                        {source.endpoint_url}
                      </code>
                      <CopyButton text={source.endpoint_url} />
                    </div>

                    {/* Domains */}
                    {source.allowed_domains.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {source.allowed_domains.map((domain) => (
                          <Badge
                            key={domain}
                            variant="secondary"
                            className="text-xs"
                          >
                            {domain}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-1">
                    <Switch
                      checked={source.enabled}
                      onCheckedChange={(checked) =>
                        toggleMutation.mutate({
                          id: source.id,
                          enabled: checked,
                        })
                      }
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      onClick={() => handleEdit(source)}
                      aria-label="Edit lead source"
                    >
                      <Pencil className="size-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8 text-destructive hover:text-destructive"
                      onClick={() => setDeleteTarget(source)}
                      aria-label="Delete lead source"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Example snippet card */}
      {sources && sources.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Integration Example</CardTitle>
            <CardDescription>
              Add this to your website to submit leads to your first lead source.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
              <code>{`fetch("${sources[0].endpoint_url}", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    first_name: "Jane",
    phone_number: "+15551234567",
    email: "jane@example.com",
    source_detail: "pricing-page"
  })
})`}</code>
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Speed-to-lead proof badge snippet */}
      {sources && sources.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Speed-to-Lead Proof Badge</CardTitle>
            <CardDescription>
              Drop this on your lead form to show your answered-within-target
              stat. It stays hidden until you enable the badge under Speed to
              Lead and have enough measured leads.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">
              <code>{`<div id="speed-to-lead-badge"></div>
<script>
  fetch("${sources[0].endpoint_url}/proof")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (p) {
      if (!p || !p.enabled || !p.headline) return;
      var el = document.getElementById("speed-to-lead-badge");
      el.textContent = p.headline + " \u00B7 last " + p.window_days + " days";
      el.style.cssText =
        "display:inline-flex;align-items:center;gap:8px;" +
        "border-radius:9999px;border:1px solid #a7f3d0;" +
        "background:#ecfdf5;color:#065f46;padding:6px 12px;" +
        "font:500 14px system-ui,sans-serif;";
    });
</script>`}</code>
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Create/Edit Dialog */}
      {dialogOpen && workspaceId && (
        <LeadSourceDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          source={editingSource}
          workspaceId={workspaceId}
        />
      )}

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Lead Source</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete &quot;{deleteTarget?.name}&quot;?
              The public endpoint will stop accepting submissions immediately.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() =>
                deleteTarget && deleteMutation.mutate(deleteTarget.id)
              }
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
