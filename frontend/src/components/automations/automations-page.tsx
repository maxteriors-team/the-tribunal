"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
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
  UserCheck,
  ArrowRight,
  Settings2,
  Loader2,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useQuery } from "@tanstack/react-query";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import {
  useAutomations,
  useCreateAutomation,
  useUpdateAutomation,
  useDeleteAutomation,
  useToggleAutomation,
} from "@/hooks/useAutomations";
import { automationsApi } from "@/lib/api/automations";
import type { Automation, AutomationTriggerType, AutomationActionType } from "@/types";
import { formatDate } from "@/lib/utils/date";

const triggerTypeConfig: Record<AutomationTriggerType, { label: string; icon: LucideIcon; color: string }> = {
  event: { label: "Event", icon: Zap, color: "text-warning" },
  schedule: { label: "Schedule", icon: Clock, color: "text-info" },
  condition: { label: "Condition", icon: Settings2, color: "text-primary" },
};

const actionTypeConfig: Record<AutomationActionType, { label: string; icon: LucideIcon }> = {
  send_sms: { label: "Send SMS", icon: MessageSquare },
  send_email: { label: "Send Email", icon: Mail },
  make_call: { label: "Make Call", icon: Phone },
  update_status: { label: "Update Status", icon: Settings2 },
  add_tag: { label: "Add Tag", icon: Tag },
  assign_agent: { label: "Assign Agent", icon: UserCheck },
};

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
  const [editingAutomation, setEditingAutomation] = useState<Automation | null>(null);

  const { data, isPending, error } = useAutomations(workspaceId ?? "");
  const { data: statsData } = useQuery({
    queryKey: queryKeys.automations.stats(workspaceId ?? ""),
    queryFn: () => automationsApi.getStats(workspaceId!),
    enabled: !!workspaceId,
  });
  const createMutation = useCreateAutomation(workspaceId ?? "");
  const updateMutation = useUpdateAutomation(workspaceId ?? "");
  const deleteMutation = useDeleteAutomation(workspaceId ?? "");
  const toggleMutation = useToggleAutomation(workspaceId ?? "");

  const automations = data?.items ?? [];

  const filteredAutomations = automations.filter(
    (automation) =>
      automation.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      automation.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const activeCount = automations.filter((a) => a.is_active).length;

  const handleCreateAutomation = async () => {
    if (!newAutomationName.trim()) {
      toast.error("Please enter a name for the automation");
      return;
    }

    try {
      if (editingAutomation) {
        await updateMutation.mutateAsync({
          id: editingAutomation.id,
          data: {
            name: newAutomationName,
            description: newAutomationDescription || undefined,
            trigger_type: newTriggerType,
            actions: [{ type: newActionType, config: {} }],
          },
        });
        toast.success("Automation updated successfully");
        setEditingAutomation(null);
      } else {
        await createMutation.mutateAsync({
          name: newAutomationName,
          description: newAutomationDescription || undefined,
          trigger_type: newTriggerType,
          trigger_config: {},
          actions: [{ type: newActionType, config: {} }],
          is_active: true,
        });
        toast.success("Automation created successfully");
      }
      setIsCreateDialogOpen(false);
      setNewAutomationName("");
      setNewAutomationDescription("");
      setNewTriggerType("event");
      setNewActionType("send_sms");
    } catch {
      toast.error(editingAutomation ? "Failed to update automation" : "Failed to create automation");
    }
  };

  const handleConfigureAutomation = (automation: Automation) => {
    setNewAutomationName(automation.name);
    setNewAutomationDescription(automation.description ?? "");
    setNewTriggerType(automation.trigger_type);
    setNewActionType(automation.actions[0]?.type ?? "send_sms");
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
              setNewAutomationName("");
              setNewAutomationDescription("");
              setNewTriggerType("event");
              setNewActionType("send_sms");
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
                    <SelectItem value="event">
                      <div className="flex items-center gap-2">
                        <Zap className="size-4 text-warning" />
                        Event-based
                      </div>
                    </SelectItem>
                    <SelectItem value="schedule">
                      <div className="flex items-center gap-2">
                        <Clock className="size-4 text-info" />
                        Scheduled
                      </div>
                    </SelectItem>
                    <SelectItem value="condition">
                      <div className="flex items-center gap-2">
                        <Settings2 className="size-4 text-primary" />
                        Condition-based
                      </div>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
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
                    <SelectItem value="send_sms">Send SMS</SelectItem>
                    <SelectItem value="send_email">Send Email</SelectItem>
                    <SelectItem value="make_call">Make Call</SelectItem>
                    <SelectItem value="add_tag">Add Tag</SelectItem>
                    <SelectItem value="assign_agent">Assign Agent</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setIsCreateDialogOpen(false);
                  setEditingAutomation(null);
                  setNewAutomationName("");
                  setNewAutomationDescription("");
                  setNewTriggerType("event");
                  setNewActionType("send_sms");
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
              const trigger = triggerTypeConfig[automation.trigger_type];
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
                            {automation.trigger_type === "event" && "When a contact is created"}
                            {automation.trigger_type === "schedule" && "Runs on schedule"}
                            {automation.trigger_type === "condition" && "When conditions are met"}
                          </p>
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
                          return (
                            <div
                              key={index}
                              className="flex items-center gap-3 p-2 rounded-lg border"
                            >
                              <ActionIcon className="size-4 text-muted-foreground" />
                              <span className="text-sm">{actionConfig.label}</span>
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
