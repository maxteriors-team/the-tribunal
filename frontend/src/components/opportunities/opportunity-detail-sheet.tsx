"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DollarSign,
  Calendar,
  Edit2,
  Trash2,
  MoreVertical,
  Check,
  X,
  Clock,
  ArrowRight,
  CircleDot,
  Trophy,
  XCircle,
  Archive,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { opportunityStatusColors } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import { formatDate, formatDateTime } from "@/lib/utils/date";
import type { Opportunity, OpportunityStatus, OpportunityActivity } from "@/types";


interface OpportunityDetailSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  opportunity: Opportunity | null;
  workspaceId: string;
}

interface OpportunityEditData {
  name: string;
  description: string;
  amount: string;
  currency: string;
  expected_close_date: string;
  source: string;
  status: OpportunityStatus;
  lost_reason: string;
}

function getOpportunityEditData(opportunity: Opportunity | null): OpportunityEditData {
  return {
    name: opportunity?.name ?? "",
    description: opportunity?.description ?? "",
    amount: opportunity?.amount?.toString() ?? "",
    currency: opportunity?.currency ?? "USD",
    expected_close_date: opportunity?.expected_close_date ?? "",
    source: opportunity?.source ?? "",
    status: opportunity?.status ?? "open",
    lost_reason: opportunity?.lost_reason ?? "",
  };
}

function formatCurrency(amount: number | undefined, currency: string) {
  if (!amount) return "$0";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency,
  }).format(amount);
}

function getStatusConfig(status: OpportunityStatus) {
  switch (status) {
    case "won":
      return {
        label: "Won",
        color: opportunityStatusColors.won,
        icon: Trophy,
      };
    case "lost":
      return {
        label: "Lost",
        color: opportunityStatusColors.lost,
        icon: XCircle,
      };
    case "abandoned":
      return {
        label: "Abandoned",
        color: opportunityStatusColors.abandoned,
        icon: Archive,
      };
    default:
      return {
        label: "Open",
        color: opportunityStatusColors.open,
        icon: CircleDot,
      };
  }
}

interface ActivityItemProps {
  activity: OpportunityActivity;
}

function ActivityItem({ activity }: ActivityItemProps) {
  const getActivityIcon = () => {
    switch (activity.activity_type) {
      case "stage_changed":
        return <ArrowRight className="h-4 w-4 text-info" />;
      case "status_changed":
        return <CircleDot className="h-4 w-4 text-primary" />;
      default:
        return <Clock className="h-4 w-4 text-muted-foreground" />;
    }
  };

  return (
    <div className="flex gap-3 py-3">
      <div className="flex-shrink-0 mt-0.5">{getActivityIcon()}</div>
      <div className="flex-1 min-w-0">
        <p className="text-sm">{activity.description}</p>
        <p className="text-xs text-muted-foreground mt-1">
          {formatDateTime(activity.created_at)}
        </p>
      </div>
    </div>
  );
}

export function OpportunityDetailSheet({
  open,
  onOpenChange,
  opportunity,
  workspaceId,
}: OpportunityDetailSheetProps) {
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const initialEditData = useMemo(
    () => getOpportunityEditData(opportunity),
    [opportunity]
  );
  const [editData, setEditData] = useState(initialEditData);

  // Fetch full opportunity details with activities
  const { data: opportunityDetail } = useQuery({
    queryKey: queryKeys.opportunities.detail(workspaceId ?? "", opportunity?.id),
    queryFn: () =>
      opportunity ? opportunitiesApi.get(workspaceId, opportunity.id) : null,
    enabled: !!opportunity && open,
  });

  // Fetch pipelines for stage selector
  const { data: pipelines } = useQuery({
    queryKey: queryKeys.opportunities.pipelines(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.listPipelines(workspaceId),
    enabled: !!workspaceId && open,
  });

  // Find current pipeline and stage
  const currentPipeline = pipelines?.find(
    (p) => p.id === opportunity?.pipeline_id
  );
  const currentStage = currentPipeline?.stages.find(
    (s) => s.id === opportunity?.stage_id
  );

  const startEditing = () => {
    setEditData(initialEditData);
    setIsEditing(true);
  };

  const cancelEditing = () => {
    setEditData(initialEditData);
    setIsEditing(false);
  };

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof opportunitiesApi.update>[2]) =>
      opportunitiesApi.update(workspaceId, opportunity!.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId ?? ""),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.detail(workspaceId ?? "", opportunity?.id),
      });
      setIsEditing(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => opportunitiesApi.delete(workspaceId, opportunity!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId ?? ""),
      });
      onOpenChange(false);
    },
  });

  const handleSave = () => {
    if (!opportunity) return;
    updateMutation.mutate({
      name: editData.name,
      description: editData.description || undefined,
      amount: editData.amount ? parseFloat(editData.amount) : undefined,
      currency: editData.currency,
      expected_close_date: editData.expected_close_date || undefined,
      source: editData.source || undefined,
      status: editData.status,
      lost_reason: editData.lost_reason || undefined,
    });
  };

  const handleStatusChange = (newStatus: OpportunityStatus) => {
    if (!opportunity) return;
    updateMutation.mutate({ status: newStatus });
  };

  const handleStageChange = (stageId: string) => {
    if (!opportunity) return;
    updateMutation.mutate({ stage_id: stageId });
  };

  if (!opportunity) return null;

  const statusConfig = getStatusConfig(opportunity.status);
  const StatusIcon = statusConfig.icon;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-[500px] flex flex-col p-0">
        <SheetHeader className="p-6 pb-0">
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <SheetTitle className="text-xl">{opportunity.name}</SheetTitle>
              <SheetDescription className="mt-1">
                {currentPipeline?.name} • {currentStage?.name || "No stage"}
              </SheetDescription>
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Opportunity actions">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={startEditing}>
                  <Edit2 className="h-4 w-4 mr-2" />
                  Edit
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => deleteMutation.mutate()}
                  className="text-destructive"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </SheetHeader>

        <ScrollArea className="flex-1">
          <div className="p-6 space-y-6">
            {/* Status Badge */}
            <div className="flex items-center gap-3">
              <Badge
                variant="outline"
                className={cn("text-sm py-1 px-3", statusConfig.color)}
              >
                <StatusIcon className="h-4 w-4 mr-1.5" />
                {statusConfig.label}
              </Badge>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    Change Status
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onClick={() => handleStatusChange("open")}>
                    <CircleDot className="h-4 w-4 mr-2 text-info" />
                    Open
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleStatusChange("won")}>
                    <Trophy className="h-4 w-4 mr-2 text-success" />
                    Won
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleStatusChange("lost")}>
                    <XCircle className="h-4 w-4 mr-2 text-destructive" />
                    Lost
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => handleStatusChange("abandoned")}
                  >
                    <Archive className="h-4 w-4 mr-2 text-muted-foreground" />
                    Abandoned
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            {/* Quick Info */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Value</p>
                <p className="text-lg font-semibold flex items-center">
                  <DollarSign className="h-4 w-4 mr-1" />
                  {formatCurrency(opportunity.amount, opportunity.currency)}
                </p>
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Probability</p>
                <p className="text-lg font-semibold">{opportunity.probability}%</p>
              </div>
              {opportunity.expected_close_date && (
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Expected Close</p>
                  <p className="text-sm flex items-center">
                    <Calendar className="h-4 w-4 mr-1" />
                    {formatDate(opportunity.expected_close_date)}
                  </p>
                </div>
              )}
              {opportunity.source && (
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Source</p>
                  <p className="text-sm">{opportunity.source}</p>
                </div>
              )}
            </div>

            {/* Stage Selector */}
            {currentPipeline && (
              <>
                <Separator />
                <div className="space-y-3">
                  <Label>Stage</Label>
                  <Select
                    value={opportunity.stage_id || ""}
                    onValueChange={handleStageChange}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select stage" />
                    </SelectTrigger>
                    <SelectContent>
                      {currentPipeline.stages
                        .sort((a, b) => a.order - b.order)
                        .map((stage) => (
                          <SelectItem key={stage.id} value={stage.id}>
                            {stage.name} ({stage.probability}%)
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}

            {/* Description */}
            {opportunity.description && (
              <>
                <Separator />
                <div className="space-y-2">
                  <Label>Description</Label>
                  <p className="text-sm text-muted-foreground">
                    {opportunity.description}
                  </p>
                </div>
              </>
            )}

            {/* Edit Form */}
            {isEditing && (
              <>
                <Separator />
                <div className="space-y-4">
                  <h3 className="font-medium">Edit Opportunity</h3>
                  <div className="space-y-2">
                    <Label htmlFor="edit-name">Name</Label>
                    <Input
                      id="edit-name"
                      value={editData.name}
                      onChange={(e) =>
                        setEditData({ ...editData, name: e.target.value })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-description">Description</Label>
                    <Textarea
                      id="edit-description"
                      value={editData.description}
                      onChange={(e) =>
                        setEditData({ ...editData, description: e.target.value })
                      }
                      rows={3}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="edit-amount">Amount</Label>
                      <Input
                        id="edit-amount"
                        type="number"
                        value={editData.amount}
                        onChange={(e) =>
                          setEditData({ ...editData, amount: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="edit-currency">Currency</Label>
                      <Select
                        value={editData.currency}
                        onValueChange={(v) =>
                          setEditData({ ...editData, currency: v })
                        }
                      >
                        <SelectTrigger id="edit-currency">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="USD">USD</SelectItem>
                          <SelectItem value="EUR">EUR</SelectItem>
                          <SelectItem value="GBP">GBP</SelectItem>
                          <SelectItem value="CAD">CAD</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-close-date">Expected Close Date</Label>
                    <Input
                      id="edit-close-date"
                      type="date"
                      value={editData.expected_close_date}
                      onChange={(e) =>
                        setEditData({
                          ...editData,
                          expected_close_date: e.target.value,
                        })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-source">Source</Label>
                    <Input
                      id="edit-source"
                      value={editData.source}
                      onChange={(e) =>
                        setEditData({ ...editData, source: e.target.value })
                      }
                      placeholder="e.g., Website, Referral, Campaign"
                    />
                  </div>
                  {editData.status === "lost" && (
                    <div className="space-y-2">
                      <Label htmlFor="edit-lost-reason">Lost Reason</Label>
                      <Input
                        id="edit-lost-reason"
                        value={editData.lost_reason}
                        onChange={(e) =>
                          setEditData({ ...editData, lost_reason: e.target.value })
                        }
                        placeholder="Why was this opportunity lost?"
                      />
                    </div>
                  )}
                  <div className="flex gap-2">
                    <Button
                      onClick={handleSave}
                      disabled={updateMutation.isPending}
                    >
                      <Check className="h-4 w-4 mr-1" />
                      {updateMutation.isPending ? "Saving..." : "Save"}
                    </Button>
                    <Button
                      variant="outline"
                      onClick={cancelEditing}
                    >
                      <X className="h-4 w-4 mr-1" />
                      Cancel
                    </Button>
                  </div>
                </div>
              </>
            )}

            {/* Activity Timeline */}
            <Separator />
            <div className="space-y-3">
              <h3 className="font-medium">Activity</h3>
              {opportunityDetail?.activities &&
              opportunityDetail.activities.length > 0 ? (
                <div className="divide-y">
                  {opportunityDetail.activities
                    .sort(
                      (a, b) =>
                        new Date(b.created_at).getTime() -
                        new Date(a.created_at).getTime()
                    )
                    .map((activity) => (
                      <ActivityItem key={activity.id} activity={activity} />
                    ))}
                </div>
              ) : (
                <div className="text-center py-6 text-muted-foreground text-sm">
                  No activity yet
                </div>
              )}
            </div>

            {/* Metadata */}
            <Separator />
            <div className="text-xs text-muted-foreground space-y-1">
              <p>Created: {formatDateTime(opportunity.created_at)}</p>
              <p>Updated: {formatDateTime(opportunity.updated_at)}</p>
              {opportunity.stage_changed_at && (
                <p>
                  Stage changed:{" "}
                  {formatDateTime(opportunity.stage_changed_at)}
                </p>
              )}
            </div>
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
