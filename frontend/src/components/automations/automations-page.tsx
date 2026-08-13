"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Plus,
  Search,
  MoreHorizontal,
  Play,
  Pause,
  Copy,
  Trash2,
  Zap,
  Clock,
  Tag,
  ArrowRight,
  Settings2,
  Loader2,
  Star,
  TrendingUp,
  PhoneMissed,
  GraduationCap,
  FileText,
  CalendarCheck,
  CalendarX,
  UserPlus,
  Gauge,
  FileCheck,
  FileX,
  Receipt,
  BadgeCheck,
  BadgeDollarSign,
  CalendarClock,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { useState } from "react";
import { toast } from "sonner";

import {
  BACKLOG_DEFAULT_THRESHOLD_WEEKS,
  buildBacklogTriggerConfig,
  defaultBacklogTriggerInputs,
  describeBacklogTrigger,
  parseBacklogTriggerConfig,
  validateBacklogTriggerInputs,
} from "@/components/automations/backlog-trigger";
import {
  describeBranchStep,
  describeWaitStep,
  isWaitAction,
  normalizeSteps,
  validateSteps,
} from "@/components/automations/workflow-steps";
import {
  WorkflowStepsEditor,
  actionMeta,
} from "@/components/automations/workflow-steps-editor";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
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
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  useAutomations,
  useCreateAutomation,
  useUpdateAutomation,
  useDeleteAutomation,
  useToggleAutomation,
} from "@/hooks/useAutomations";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { automationsApi } from "@/lib/api/automations";
import { dripCampaignsApi } from "@/lib/api/drip-campaigns";
import { leadSourcesApi } from "@/lib/api/lead-sources";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { tagsApi } from "@/lib/api/tags";
import { queryKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils/date";
import type {
  Automation,
  AutomationAction,
  AutomationTriggerType,
} from "@/types";

const triggerTypeConfig: Record<AutomationTriggerType, { label: string; icon: LucideIcon; color: string; description: string }> = {
  event: { label: "Event", icon: Zap, color: "text-warning", description: "When an event occurs" },
  schedule: { label: "Schedule", icon: Clock, color: "text-info", description: "Runs on a schedule" },
  condition: { label: "Condition", icon: Settings2, color: "text-primary", description: "When conditions are met" },
  appointment_booked: { label: "Appointment Booked", icon: CalendarCheck, color: "text-success", description: "When a qualified lead books a CRM appointment" },
  booking_created: { label: "Booking Created", icon: CalendarCheck, color: "text-success", description: "When a booking is created" },
  no_show: { label: "No-show", icon: CalendarX, color: "text-destructive", description: "When a contact misses an appointment" },
  contact_tagged: { label: "Contact Tagged", icon: Tag, color: "text-primary", description: "When a contact gets a specific tag" },
  never_booked: { label: "Never Booked", icon: UserPlus, color: "text-warning", description: "When a contact never booked after engaging" },
  backlog_below_threshold: { label: "Backlog Below Threshold", icon: Gauge, color: "text-warning", description: "When booked work drops below your threshold" },
  review_received: { label: "Review Received", icon: Star, color: "text-warning", description: "When a new review or rating comes in" },
  review_request_response: { label: "Review Request Response", icon: Star, color: "text-warning", description: "When a contact responds to a review request" },
  opportunity_created: { label: "Opportunity Created", icon: TrendingUp, color: "text-success", description: "When a new deal is created" },
  deal_stage_changed: { label: "Deal Stage Changed", icon: TrendingUp, color: "text-info", description: "When a deal moves to a new stage" },
  missed_call: { label: "Missed Call", icon: PhoneMissed, color: "text-destructive", description: "When an inbound call goes unanswered" },
  roleplay_completed: { label: "Roleplay Completed", icon: GraduationCap, color: "text-primary", description: "When a practice-arena rehearsal finishes" },
  knowledge_document_uploaded: { label: "Knowledge Doc Uploaded", icon: FileText, color: "text-info", description: "When a knowledge document is added" },
  lead_created: { label: "New Lead Captured", icon: UserPlus, color: "text-success", description: "When a new lead is captured from a lead source" },
  lead_qualified: { label: "Lead Qualified", icon: BadgeCheck, color: "text-success", description: "When AI validates a lead's qualification evidence and score" },
  quote_sent: { label: "Quote Sent", icon: FileText, color: "text-info", description: "When a quote goes out to a customer" },
  quote_approved: { label: "Quote Approved", icon: FileCheck, color: "text-success", description: "When a customer approves a quote" },
  quote_declined: { label: "Quote Declined", icon: FileX, color: "text-destructive", description: "When a customer declines a quote" },
  quote_converted: { label: "Quote Converted", icon: FileCheck, color: "text-success", description: "When a quote becomes a job or invoice" },
  invoice_sent: { label: "Invoice Sent", icon: Receipt, color: "text-info", description: "When an invoice is sent" },
  invoice_paid: { label: "Invoice Paid", icon: BadgeDollarSign, color: "text-success", description: "When an invoice is paid" },
  job_scheduled: { label: "Job Scheduled", icon: CalendarClock, color: "text-info", description: "When a job gets a date on the calendar" },
  job_completed: { label: "Job Completed", icon: Wrench, color: "text-success", description: "When a job is marked complete — the moment to send resources or ask for a review" },
};

// Triggers offered in the builder dropdown, grouped for readability.
const TRIGGER_OPTIONS: { group: string; values: AutomationTriggerType[] }[] = [
  { group: "General", values: ["event", "schedule", "condition"] },
  { group: "Leads", values: ["lead_created", "lead_qualified"] },
  { group: "Capacity", values: ["backlog_below_threshold"] },
  { group: "Appointments", values: ["appointment_booked", "booking_created", "no_show", "never_booked"] },
  { group: "Contacts & Pipeline", values: ["contact_tagged", "opportunity_created", "deal_stage_changed"] },
  { group: "Engagement", values: ["review_received", "review_request_response", "missed_call", "roleplay_completed", "knowledge_document_uploaded"] },
  { group: "Quotes & Invoices", values: ["quote_sent", "quote_approved", "quote_declined", "quote_converted", "invoice_sent", "invoice_paid"] },
  { group: "Jobs", values: ["job_scheduled", "job_completed"] },
];

// Sentinel for the "any lead source" option: Radix Select items can't use an
// empty-string value, so we map this back to "" (match every new lead).
const ALL_LEAD_SOURCES = "__all__";

// A brand-new workflow starts with one step; the builder never allows zero,
// since an automation with no steps fires and does nothing.
const defaultSteps = (): AutomationAction[] => [{ type: "send_sms", config: {} }];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
};

function AutomationCardSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="space-y-2">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-60" />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-10 w-full" />
      </CardContent>
      <CardFooter className="border-t pt-4">
        <Skeleton className="h-4 w-full" />
      </CardFooter>
    </Card>
  );
}

export function AutomationsPage() {
  const workspaceId = useWorkspaceId();
  const [searchQuery, setSearchQuery] = useState("");
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [newAutomationName, setNewAutomationName] = useState("");
  const [newAutomationDescription, setNewAutomationDescription] = useState("");
  const [newTriggerType, setNewTriggerType] = useState<AutomationTriggerType>("event");
  // The workflow itself: a flat, ordered list of steps. Whole step objects are
  // held in state (not one field per action setting) so config keys the builder
  // doesn't surface — an SMS body, a branch's step id — survive an edit.
  const [newSteps, setNewSteps] = useState<AutomationAction[]>(defaultSteps);
  // Lead-source public_key that narrows a lead_created trigger to one form
  // ("" = every new lead); tag that fires a contact_tagged trigger (service
  // line, e.g. "Landscape Lighting").
  const [newLeadSourceKey, setNewLeadSourceKey] = useState("");
  const [newTriggerTag, setNewTriggerTag] = useState("");
  // backlog_below_threshold settings: fire under this many weeks of booked work,
  // then stay silent for this many days so a slow month can't re-blast everyone.
  const [newBacklogInputs, setNewBacklogInputs] = useState(defaultBacklogTriggerInputs);
  const [editingAutomation, setEditingAutomation] = useState<Automation | null>(null);

  const { data, isPending, error } = useAutomations(workspaceId ?? "");
  const { data: statsData } = useQuery({
    queryKey: queryKeys.automations.stats(workspaceId ?? ""),
    queryFn: () => automationsApi.getStats(workspaceId!),
    enabled: !!workspaceId,
  });
  const { data: leadSourcesData } = useQuery({
    queryKey: queryKeys.leadSources.all(workspaceId ?? ""),
    queryFn: () => leadSourcesApi.list(workspaceId!),
    enabled: !!workspaceId,
  });
  const { data: tagsData } = useQuery({
    queryKey: queryKeys.tags.all(workspaceId ?? ""),
    queryFn: () => tagsApi.list(workspaceId!),
    enabled: !!workspaceId,
  });
  const { data: pipelinesData } = useQuery({
    queryKey: queryKeys.opportunities.pipelines(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.listPipelines(workspaceId!),
    enabled: !!workspaceId,
  });
  const { data: dripCampaignsData } = useQuery({
    queryKey: queryKeys.dripCampaigns.all(workspaceId ?? ""),
    queryFn: () => dripCampaignsApi.list(workspaceId!),
    enabled: !!workspaceId,
  });
  const createMutation = useCreateAutomation(workspaceId ?? "");
  const updateMutation = useUpdateAutomation(workspaceId ?? "");
  const deleteMutation = useDeleteAutomation(workspaceId ?? "");
  const toggleMutation = useToggleAutomation(workspaceId ?? "");

  const automations = data?.items ?? [];
  const leadSources = leadSourcesData ?? [];
  const tagOptions = tagsData?.items ?? [];
  const isTagTrigger = newTriggerType === "contact_tagged";
  const isBacklogTrigger = newTriggerType === "backlog_below_threshold";
  const pipelines = pipelinesData ?? [];
  // A completed sequence can't be restarted, so the builder doesn't offer one.
  const dripCampaigns = (dripCampaignsData ?? []).filter(
    (campaign) => campaign.status !== "completed"
  );
  const dripCampaignNameById = (id: string): string | undefined =>
    dripCampaigns.find((campaign) => campaign.id === id)?.name;
  // Resolve a stored stage_id to its display name for the action chip.
  const stageNameById = (stageId: string): string | undefined => {
    for (const pipeline of pipelines) {
      const stage = pipeline.stages?.find((s) => s.id === stageId);
      if (stage) return stage.name;
    }
    return undefined;
  };
  const leadSourceNameByKey = (key: string) =>
    leadSources.find((source) => source.public_key === key)?.name ?? key;

  const filteredAutomations = automations.filter(
    (automation) =>
      automation.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      automation.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const activeCount = automations.filter((a) => a.is_active).length;

  const resetForm = () => {
    setNewAutomationName("");
    setNewAutomationDescription("");
    setNewTriggerType("event");
    setNewSteps(defaultSteps());
    setNewLeadSourceKey("");
    setNewTriggerTag("");
    setNewBacklogInputs(defaultBacklogTriggerInputs());
  };

  // Narrow a lead_created automation to one lead source, or clear the selector
  // for an "any new lead" trigger. Unrelated selectors set via the API survive.
  const buildTriggerConfig = (): Record<string, unknown> => {
    const config: Record<string, unknown> =
      editingAutomation && editingAutomation.trigger_type === newTriggerType
        ? { ...(editingAutomation.trigger_config ?? {}) }
        : {};
    if (newTriggerType === "lead_created") {
      if (newLeadSourceKey) {
        config.lead_source_public_key = newLeadSourceKey;
      } else {
        delete config.lead_source_public_key;
      }
    }
    // contact_tagged fires for contacts carrying this exact tag; the worker
    // reads trigger_config.tag, so an empty value would never match.
    if (newTriggerType === "contact_tagged") {
      config.tag = newTriggerTag.trim();
    }
    // Weeks-of-work threshold plus the mandatory cooldown between fires.
    if (newTriggerType === "backlog_below_threshold") {
      Object.assign(config, buildBacklogTriggerConfig(newBacklogInputs));
    }
    return config;
  };

  const handleCreateAutomation = async () => {
    if (!newAutomationName.trim()) {
      toast.error("Please enter a name for the automation");
      return;
    }
    if (newTriggerType === "contact_tagged" && !newTriggerTag.trim()) {
      toast.error("Pick the tag that should trigger this automation");
      return;
    }
    const stepsError = validateSteps(newSteps);
    if (stepsError) {
      toast.error(stepsError);
      return;
    }
    if (isBacklogTrigger) {
      const backlogError = validateBacklogTriggerInputs(newBacklogInputs);
      if (backlogError) {
        toast.error(backlogError);
        return;
      }
    }

    try {
      if (editingAutomation) {
        await updateMutation.mutateAsync({
          id: editingAutomation.id,
          data: {
            name: newAutomationName,
            description: newAutomationDescription || undefined,
            trigger_type: newTriggerType,
            trigger_config: buildTriggerConfig(),
            actions: normalizeSteps(newSteps),
          },
        });
        toast.success("Automation updated successfully");
        setEditingAutomation(null);
      } else {
        await createMutation.mutateAsync({
          name: newAutomationName,
          description: newAutomationDescription || undefined,
          trigger_type: newTriggerType,
          trigger_config: buildTriggerConfig(),
          actions: normalizeSteps(newSteps),
          is_active: true,
        });
        toast.success("Automation created successfully");
      }
      setIsCreateDialogOpen(false);
      resetForm();
    } catch {
      toast.error(editingAutomation ? "Failed to update automation" : "Failed to create automation");
    }
  };

  const handleConfigureAutomation = (automation: Automation) => {
    setNewAutomationName(automation.name);
    setNewAutomationDescription(automation.description ?? "");
    setNewTriggerType(automation.trigger_type);
    // Copy each step (config included) so edits in the dialog can't mutate the
    // cached automation before the operator saves.
    setNewSteps(
      automation.actions.length > 0
        ? automation.actions.map((action) => ({ ...action, config: { ...action.config } }))
        : defaultSteps()
    );
    setNewBacklogInputs(parseBacklogTriggerConfig(automation.trigger_config));
    const sourceKey = automation.trigger_config?.lead_source_public_key;
    setNewLeadSourceKey(typeof sourceKey === "string" ? sourceKey : "");
    const triggerTag = automation.trigger_config?.tag;
    setNewTriggerTag(typeof triggerTag === "string" ? triggerTag : "");
    setEditingAutomation(automation);
  };

  const handleToggleAutomation = async (automation: Automation) => {
    try {
      await toggleMutation.mutateAsync(automation.id);
      toast.success(automation.is_active ? "Automation paused" : "Automation activated");
    } catch {
      toast.error("Failed to toggle automation");
    }
  };

  const handleDeleteAutomation = async (automation: Automation) => {
    try {
      await deleteMutation.mutateAsync(automation.id);
      toast.success("Automation deleted");
    } catch {
      toast.error("Failed to delete automation");
    }
  };

  const handleDuplicateAutomation = async (automation: Automation) => {
    try {
      await createMutation.mutateAsync({
        name: `${automation.name} (Copy)`,
        description: automation.description,
        trigger_type: automation.trigger_type,
        trigger_config: automation.trigger_config,
        actions: automation.actions,
        is_active: false,
      });
      toast.success("Automation duplicated");
    } catch {
      toast.error("Failed to duplicate automation");
    }
  };

  if (error) {
    return (
      <div className="p-6">
        <PageErrorState message="Failed to load automations" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Automations</h1>
          <p className="text-muted-foreground">
            Create workflows to automate repetitive tasks
          </p>
        </div>
        <Dialog
          open={isCreateDialogOpen || !!editingAutomation}
          onOpenChange={(open) => {
            if (!open) {
              setIsCreateDialogOpen(false);
              setEditingAutomation(null);
              resetForm();
            }
          }}
        >
          <DialogTrigger asChild>
            <Button onClick={() => { setEditingAutomation(null); setIsCreateDialogOpen(true); }}>
              <Plus className="mr-2 size-4" />
              Create Automation
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>{editingAutomation ? "Configure Automation" : "Create Automation"}</DialogTitle>
              <DialogDescription>
                {editingAutomation ? "Modify the automation settings" : "Set up a new automated workflow"}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="auto-name">Name</Label>
                <Input
                  id="auto-name"
                  placeholder="e.g., New Lead Welcome"
                  value={newAutomationName}
                  onChange={(e) => setNewAutomationName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="auto-desc">Description</Label>
                <Input
                  id="auto-desc"
                  placeholder="Brief description of what this automation does"
                  value={newAutomationDescription}
                  onChange={(e) => setNewAutomationDescription(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Trigger Type</Label>
                <Select
                  value={newTriggerType}
                  onValueChange={(v) => setNewTriggerType(v as AutomationTriggerType)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TRIGGER_OPTIONS.map((group) => (
                      <SelectGroup key={group.group}>
                        <SelectLabel>{group.group}</SelectLabel>
                        {group.values.map((value) => {
                          const cfg = triggerTypeConfig[value];
                          const Icon = cfg.icon;
                          return (
                            <SelectItem key={value} value={value}>
                              <div className="flex items-center gap-2">
                                <Icon className={`size-4 ${cfg.color}`} />
                                {cfg.label}
                              </div>
                            </SelectItem>
                          );
                        })}
                      </SelectGroup>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {newTriggerType === "lead_created" && (
                <div className="space-y-2">
                  <Label>Lead source</Label>
                  <Select
                    value={newLeadSourceKey || ALL_LEAD_SOURCES}
                    onValueChange={(v) =>
                      setNewLeadSourceKey(v === ALL_LEAD_SOURCES ? "" : v)
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL_LEAD_SOURCES}>All lead sources</SelectItem>
                      {leadSources.map((source) => (
                        <SelectItem key={source.id} value={source.public_key}>
                          {source.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Run this for one form only, or leave on all lead sources to catch every new lead.
                  </p>
                </div>
              )}
              {isTagTrigger && (
                <div className="space-y-2">
                  <Label>Tag</Label>
                  {tagOptions.length > 0 ? (
                    <Select value={newTriggerTag} onValueChange={setNewTriggerTag}>
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a tag" />
                      </SelectTrigger>
                      <SelectContent>
                        {tagOptions.map((tag) => (
                          <SelectItem key={tag.id} value={tag.name}>
                            {tag.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      placeholder="e.g. Landscape Lighting"
                      value={newTriggerTag}
                      onChange={(e) => setNewTriggerTag(e.target.value)}
                    />
                  )}
                  <p className="text-xs text-muted-foreground">
                    Fires for contacts who have this exact tag, like a service line
                    (Landscape Lighting, Permanent Lighting) or Previous Client.
                  </p>
                </div>
              )}
              {isBacklogTrigger && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="auto-backlog-threshold">Fire below (weeks of work)</Label>
                    <Input
                      id="auto-backlog-threshold"
                      type="number"
                      min={0.5}
                      step={0.5}
                      value={newBacklogInputs.thresholdWeeks}
                      onChange={(e) =>
                        setNewBacklogInputs((prev) => ({
                          ...prev,
                          thresholdWeeks: e.target.value,
                        }))
                      }
                    />
                    <p className="text-xs text-muted-foreground">
                      {BACKLOG_DEFAULT_THRESHOLD_WEEKS} weeks is a common threshold for home
                      services — under that, fill the calendar now, while a new lead still has
                      time to become a job. Needs crew capacity set in Revenue Targets;
                      without it the backlog is unknown and this never fires.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="auto-backlog-cooldown">Cooldown (days)</Label>
                    <Input
                      id="auto-backlog-cooldown"
                      type="number"
                      min={1}
                      step={1}
                      value={newBacklogInputs.cooldownDays}
                      onChange={(e) =>
                        setNewBacklogInputs((prev) => ({
                          ...prev,
                          cooldownDays: e.target.value,
                        }))
                      }
                    />
                    <p className="text-xs text-muted-foreground">
                      A thin backlog stays thin, so this waits at least this many days before
                      firing again — otherwise a slow month would message your whole list
                      daily.
                    </p>
                  </div>
                </div>
              )}
              <WorkflowStepsEditor
                workspaceId={workspaceId ?? ""}
                steps={newSteps}
                onStepsChange={setNewSteps}
                pipelines={pipelines}
                dripCampaigns={dripCampaigns}
              />
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setIsCreateDialogOpen(false);
                  setEditingAutomation(null);
                  resetForm();
                }}
              >
                Cancel
              </Button>
              <Button
                onClick={handleCreateAutomation}
                disabled={createMutation.isPending || updateMutation.isPending}
              >
                {(createMutation.isPending || updateMutation.isPending) && (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                )}
                {editingAutomation ? "Save Changes" : "Create"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Automations</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isPending ? <Skeleton className="h-8 w-8" /> : automations.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Active</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-success">
              {isPending ? <Skeleton className="h-8 w-8" /> : activeCount}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Triggered Today</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isPending ? <Skeleton className="h-8 w-8" /> : statsData?.triggered_today ?? 0}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search automations..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-10"
        />
      </div>

      {/* Automations Grid */}
      {isPending ? (
        <div className="grid gap-4 md:grid-cols-2">
          <AutomationCardSkeleton />
          <AutomationCardSkeleton />
          <AutomationCardSkeleton />
          <AutomationCardSkeleton />
        </div>
      ) : filteredAutomations.length === 0 ? (
        <Card>
          <CardContent className="py-4">
            <PageEmptyState
              icon={<Zap className="size-12" />}
              title="No automations found"
              description={
                searchQuery
                  ? "Try adjusting your search"
                  : "Create your first automation to automate repetitive tasks"
              }
              action={
                !searchQuery ? (
                  <Button onClick={() => { setEditingAutomation(null); setIsCreateDialogOpen(true); }}>
                    <Plus className="mr-2 size-4" />
                    Create Automation
                  </Button>
                ) : undefined
              }
            />
          </CardContent>
        </Card>
      ) : (
        <motion.div
          className="grid gap-4 md:grid-cols-2"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          <AnimatePresence mode="popLayout">
            {filteredAutomations.map((automation) => {
              const trigger = triggerTypeConfig[automation.trigger_type] ?? {
                label: automation.trigger_type,
                icon: Zap,
                color: "text-muted-foreground",
                description: "Custom trigger",
              };
              const TriggerIcon = trigger.icon;

              return (
                <motion.div
                  key={automation.id}
                  layout
                  variants={itemVariants}
                  initial="hidden"
                  animate="visible"
                  exit={{ opacity: 0, scale: 0.9 }}
                >
                  <Card className="group">
                    <CardHeader className="pb-3">
                      <div className="flex items-start justify-between">
                        <div className="space-y-1">
                          <CardTitle className="text-lg flex items-center gap-2">
                            {automation.name}
                            {automation.is_active && (
                              <span className="size-2 rounded-full bg-success" />
                            )}
                          </CardTitle>
                          <CardDescription>{automation.description}</CardDescription>
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8 opacity-0 group-hover:opacity-100"
                              aria-label="Automation actions"
                            >
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onClick={() => handleConfigureAutomation(automation)}
                            >
                              <Settings2 className="mr-2 size-4" />
                              Configure
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => handleToggleAutomation(automation)}
                              disabled={toggleMutation.isPending}
                            >
                              {automation.is_active ? (
                                <>
                                  <Pause className="mr-2 size-4" />
                                  Pause
                                </>
                              ) : (
                                <>
                                  <Play className="mr-2 size-4" />
                                  Activate
                                </>
                              )}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => handleDuplicateAutomation(automation)}
                              disabled={createMutation.isPending}
                            >
                              <Copy className="mr-2 size-4" />
                              Duplicate
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-destructive"
                              onClick={() => handleDeleteAutomation(automation)}
                              disabled={deleteMutation.isPending}
                            >
                              <Trash2 className="mr-2 size-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {/* Trigger */}
                      <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
                        <div className={`p-2 rounded-md bg-background ${trigger.color}`}>
                          <TriggerIcon className="size-4" />
                        </div>
                        <div className="flex-1">
                          <p className="text-sm font-medium">{trigger.label} Trigger</p>
                          <p className="text-xs text-muted-foreground">
                            {trigger.description}
                          </p>
                          {automation.trigger_type === "lead_created" &&
                            typeof automation.trigger_config?.lead_source_public_key ===
                              "string" && (
                              <p className="text-xs text-muted-foreground mt-0.5">
                                Source:{" "}
                                {leadSourceNameByKey(
                                  automation.trigger_config.lead_source_public_key as string
                                )}
                              </p>
                            )}
                          {automation.trigger_type === "contact_tagged" &&
                            typeof automation.trigger_config?.tag === "string" &&
                            automation.trigger_config.tag && (
                              <p className="text-xs text-muted-foreground mt-0.5">
                                Tag: {automation.trigger_config.tag as string}
                              </p>
                            )}
                          {automation.trigger_type === "backlog_below_threshold" && (
                            <p className="text-xs text-muted-foreground mt-0.5">
                              {describeBacklogTrigger(automation.trigger_config)}
                            </p>
                          )}
                        </div>
                      </div>

                      {/* Arrow */}
                      <div className="flex justify-center">
                        <ArrowRight className="size-4 text-muted-foreground" />
                      </div>

                      {/* Actions */}
                      <div className="space-y-2">
                        {automation.actions.map((action, index) => {
                          const actionConfig = actionMeta(action.type);
                          const ActionIcon = actionConfig.icon;
                          const tagValue =
                            typeof action.config?.tag === "string" ? action.config.tag : "";
                          const stageId =
                            typeof action.config?.stage_id === "string"
                              ? action.config.stage_id
                              : "";
                          const dripId =
                            typeof action.config?.drip_campaign_id === "string"
                              ? action.config.drip_campaign_id
                              : "";
                          // Show the tag for tag actions, the resolved stage /
                          // drip-campaign name for the actions that target one,
                          // and the duration / condition count for control flow.
                          const chip =
                            action.type === "move_to_stage"
                              ? stageId
                                ? stageNameById(stageId) ?? "Stage"
                                : ""
                              : action.type === "start_drip_campaign"
                                ? dripId
                                  ? dripCampaignNameById(dripId) ?? "Drip campaign"
                                  : ""
                                : isWaitAction(action.type)
                                  ? describeWaitStep(action.config)
                                  : action.type === "branch"
                                    ? describeBranchStep(action.config)
                                    : tagValue;
                          return (
                            <div
                              key={index}
                              className="flex items-center gap-3 p-2 rounded-lg border"
                            >
                              <ActionIcon className="size-4 text-muted-foreground" />
                              <span className="text-sm">{actionConfig.label}</span>
                              {chip && (
                                <span className="ml-auto rounded bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                                  {chip}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </CardContent>
                    <CardFooter className="border-t pt-4">
                      <div className="flex items-center justify-between w-full text-sm">
                        <div className="text-muted-foreground">
                          {automation.last_triggered_at
                            ? `Last run: ${formatDate(automation.last_triggered_at)}`
                            : "Never triggered"}
                        </div>
                        <Switch
                          checked={automation.is_active}
                          onCheckedChange={() => handleToggleAutomation(automation)}
                          disabled={toggleMutation.isPending}
                        />
                      </div>
                    </CardFooter>
                  </Card>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </motion.div>
      )}
    </div>
  );
}
