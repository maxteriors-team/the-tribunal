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
  MessageSquare,
  Mail,
  Phone,
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
  Megaphone,
  Timer,
  Gauge,
  Rocket,
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
  AutomationActionType,
} from "@/types";

const triggerTypeConfig: Record<AutomationTriggerType, { label: string; icon: LucideIcon; color: string; description: string }> = {
  event: { label: "Event", icon: Zap, color: "text-warning", description: "When an event occurs" },
  schedule: { label: "Schedule", icon: Clock, color: "text-info", description: "Runs on a schedule" },
  condition: { label: "Condition", icon: Settings2, color: "text-primary", description: "When conditions are met" },
  appointment_booked: { label: "Appointment Booked", icon: CalendarCheck, color: "text-success", description: "When a contact books an appointment" },
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
};

const actionTypeConfig: Record<AutomationActionType, { label: string; icon: LucideIcon }> = {
  send_sms: { label: "Send SMS", icon: MessageSquare },
  send_email: { label: "Send Email", icon: Mail },
  make_call: { label: "Make Call", icon: Phone },
  enroll_campaign: { label: "Enroll in Campaign", icon: Megaphone },
  start_drip_campaign: { label: "Start Drip Campaign", icon: Rocket },
  apply_tag: { label: "Apply Tag", icon: Tag },
  add_tag: { label: "Add Tag", icon: Tag },
  move_to_stage: { label: "Move Deal Stage", icon: TrendingUp },
  wait: { label: "Wait", icon: Timer },
  delay: { label: "Delay", icon: Timer },
  update_status: { label: "Update Status", icon: Settings2 },
};

// Triggers offered in the builder dropdown, grouped for readability.
const TRIGGER_OPTIONS: { group: string; values: AutomationTriggerType[] }[] = [
  { group: "General", values: ["event", "schedule", "condition"] },
  { group: "Leads", values: ["lead_created"] },
  { group: "Capacity", values: ["backlog_below_threshold"] },
  { group: "Appointments", values: ["appointment_booked", "booking_created", "no_show", "never_booked"] },
  { group: "Contacts & Pipeline", values: ["contact_tagged", "opportunity_created", "deal_stage_changed"] },
  { group: "Engagement", values: ["review_received", "review_request_response", "missed_call", "roleplay_completed", "knowledge_document_uploaded"] },
];

// Actions offered in the builder dropdown.
const ACTION_OPTIONS: AutomationActionType[] = [
  "send_sms",
  "send_email",
  "make_call",
  "enroll_campaign",
  "start_drip_campaign",
  "apply_tag",
  "move_to_stage",
  "wait",
];

// Actions that tag the contact and therefore need a tag-name value. An empty
// tag makes the worker skip the action, so the builder requires one.
const TAG_ACTIONS: AutomationActionType[] = ["apply_tag", "add_tag"];

// Sentinel for the "any lead source" option: Radix Select items can't use an
// empty-string value, so we map this back to "" (match every new lead).
const ALL_LEAD_SOURCES = "__all__";

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
  const [newActionType, setNewActionType] = useState<AutomationActionType>("send_sms");
  // Tag name for apply_tag/add_tag actions; lead-source public_key that narrows
  // a lead_created trigger to one form ("" = every new lead); tag that fires a
  // contact_tagged trigger (service line, e.g. "Landscape Lighting").
  const [newTagValue, setNewTagValue] = useState("");
  const [newLeadSourceKey, setNewLeadSourceKey] = useState("");
  const [newTriggerTag, setNewTriggerTag] = useState("");
  // Destination stage for a move_to_stage action; the owning pipeline is stored
  // alongside it for builder context / opportunity disambiguation.
  const [newStageId, setNewStageId] = useState("");
  const [newStagePipelineId, setNewStagePipelineId] = useState("");
  // backlog_below_threshold settings: fire under this many weeks of booked work,
  // then stay silent for this many days so a slow month can't re-blast everyone.
  const [newBacklogInputs, setNewBacklogInputs] = useState(defaultBacklogTriggerInputs);
  // Drip sequence a start_drip_campaign action switches on.
  const [newDripCampaignId, setNewDripCampaignId] = useState("");
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
  const isTagAction = TAG_ACTIONS.includes(newActionType);
  const isStageAction = newActionType === "move_to_stage";
  const isDripAction = newActionType === "start_drip_campaign";
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
    setNewActionType("send_sms");
    setNewTagValue("");
    setNewLeadSourceKey("");
    setNewTriggerTag("");
    setNewStageId("");
    setNewStagePipelineId("");
    setNewBacklogInputs(defaultBacklogTriggerInputs());
    setNewDripCampaignId("");
  };

  // Build the first action's config from the builder fields while preserving
  // any config keys the builder doesn't surface (e.g. an existing SMS body), so
  // editing an automation's name never blanks its action settings.
  const buildActions = (): AutomationAction[] => {
    const config: Record<string, unknown> =
      editingAutomation?.actions[0]?.type === newActionType
        ? { ...(editingAutomation.actions[0]?.config ?? {}) }
        : {};
    if (TAG_ACTIONS.includes(newActionType)) {
      config.tag = newTagValue.trim();
    }
    // move_to_stage stores the destination stage plus its owning pipeline (kept
    // for builder context and opportunity disambiguation on the backend).
    if (newActionType === "move_to_stage") {
      config.stage_id = newStageId;
      if (newStagePipelineId) {
        config.pipeline_id = newStagePipelineId;
      } else {
        delete config.pipeline_id;
      }
    }
    // The worker reads drip_campaign_id; without it the action is a no-op.
    if (newActionType === "start_drip_campaign") {
      config.drip_campaign_id = newDripCampaignId;
    }
    return [{ type: newActionType, config }];
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
    if (TAG_ACTIONS.includes(newActionType) && !newTagValue.trim()) {
      toast.error("Enter a tag name for the Apply Tag action");
      return;
    }
    if (newActionType === "move_to_stage" && !newStageId) {
      toast.error("Pick the stage to move the deal to");
      return;
    }
    if (newTriggerType === "contact_tagged" && !newTriggerTag.trim()) {
      toast.error("Pick the tag that should trigger this automation");
      return;
    }
    if (newActionType === "start_drip_campaign" && !newDripCampaignId) {
      toast.error("Pick the drip campaign to start");
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
            actions: buildActions(),
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
          actions: buildActions(),
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
    const firstAction = automation.actions[0];
    setNewActionType(firstAction?.type ?? "send_sms");
    setNewTagValue(typeof firstAction?.config?.tag === "string" ? firstAction.config.tag : "");
    setNewStageId(
      typeof firstAction?.config?.stage_id === "string" ? firstAction.config.stage_id : ""
    );
    setNewStagePipelineId(
      typeof firstAction?.config?.pipeline_id === "string" ? firstAction.config.pipeline_id : ""
    );
    setNewDripCampaignId(
      typeof firstAction?.config?.drip_campaign_id === "string"
        ? firstAction.config.drip_campaign_id
        : ""
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
              <div className="space-y-2">
                <Label>Action</Label>
                <Select
                  value={newActionType}
                  onValueChange={(v) => setNewActionType(v as AutomationActionType)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ACTION_OPTIONS.map((value) => {
                      const cfg = actionTypeConfig[value];
                      const Icon = cfg.icon;
                      return (
                        <SelectItem key={value} value={value}>
                          <div className="flex items-center gap-2">
                            <Icon className="size-4 text-muted-foreground" />
                            {cfg.label}
                          </div>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
              {isTagAction && (
                <div className="space-y-2">
                  <Label htmlFor="auto-tag">Tag to apply</Label>
                  <Input
                    id="auto-tag"
                    placeholder="e.g. Perm Lighting"
                    value={newTagValue}
                    onChange={(e) => setNewTagValue(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Created in this workspace if it doesn&apos;t exist yet, then added to the contact.
                  </p>
                </div>
              )}
              {isStageAction && (
                <div className="space-y-2">
                  <Label>Move deal to stage</Label>
                  {pipelines.length > 0 ? (
                    <Select
                      value={newStageId}
                      onValueChange={(v) => {
                        setNewStageId(v);
                        const owner = pipelines.find((p) =>
                          p.stages?.some((s) => s.id === v)
                        );
                        setNewStagePipelineId(owner?.id ?? "");
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a stage" />
                      </SelectTrigger>
                      <SelectContent>
                        {pipelines.map((pipeline) => (
                          <SelectGroup key={pipeline.id}>
                            <SelectLabel>{pipeline.name}</SelectLabel>
                            {[...pipeline.stages]
                              .sort((a, b) => a.order - b.order)
                              .map((stage) => (
                                <SelectItem key={stage.id} value={stage.id}>
                                  {stage.name}
                                </SelectItem>
                              ))}
                          </SelectGroup>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No pipelines yet — create one in Opportunities first.
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    When this runs, the contact&apos;s open deal is moved to this stage
                    (e.g. Estimate Scheduled).
                  </p>
                </div>
              )}
              {isDripAction && (
                <div className="space-y-2">
                  <Label>Drip campaign to start</Label>
                  {dripCampaigns.length > 0 ? (
                    <Select value={newDripCampaignId} onValueChange={setNewDripCampaignId}>
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a drip campaign" />
                      </SelectTrigger>
                      <SelectContent>
                        {dripCampaigns.map((campaign) => (
                          <SelectItem key={campaign.id} value={campaign.id}>
                            {campaign.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No drip campaigns yet — create a reactivation sequence first.
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    Switches the sequence on so its enrolled past customers start receiving
                    it. When the trigger has a contact, that contact is enrolled too.
                  </p>
                </div>
              )}
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
                          const actionConfig = actionTypeConfig[action.type] ?? {
                            label: action.type,
                            icon: Settings2,
                          };
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
                          // Show the tag for tag actions, or the resolved stage /
                          // drip-campaign name for the actions that target one.
                          const chip =
                            action.type === "move_to_stage"
                              ? stageId
                                ? stageNameById(stageId) ?? "Stage"
                                : ""
                              : action.type === "start_drip_campaign"
                                ? dripId
                                  ? dripCampaignNameById(dripId) ?? "Drip campaign"
                                  : ""
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
