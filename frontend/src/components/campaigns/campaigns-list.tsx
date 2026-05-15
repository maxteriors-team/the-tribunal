"use client";

import { useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "motion/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  MoreHorizontal,
  Play,
  Pause,
  Copy,
  Trash2,
  Mail,
  MessageSquare,
  Phone,
  Layers,
  ChevronDown,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { PageEmptyState } from "@/components/ui/page-state";
import {
  ResourceListHeader,
  ResourceListStats,
  ResourceListSearch,
  ResourceListLoading,
  ResourceListError,
  ResourceListPagination,
  ResourceListLayout,
} from "@/components/resource-list";
import { campaignStatusColors } from "@/lib/status-colors";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import type { Campaign, CampaignType } from "@/types";
import { campaignsApi } from "@/lib/api/campaigns";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";

const typeIcons: Record<CampaignType, LucideIcon> = {
  sms: MessageSquare,
  email: Mail,
  voice: Phone,
  voice_sms_fallback: Phone,
  multi_channel: Layers,
};

export function CampaignsList() {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: campaignsData, isPending, error } = useQuery({
    queryKey: queryKeys.campaigns.bare(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return campaignsApi.list(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const campaigns = campaignsData?.items ?? [];

  const pauseMutation = useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return campaignsApi.pause(workspaceId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.bare(workspaceId ?? "") });
      toast.success("Campaign paused");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to pause campaign")),
  });

  const startMutation = useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return campaignsApi.start(workspaceId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.bare(workspaceId ?? "") });
      toast.success("Campaign started");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to start campaign")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return campaignsApi.delete(workspaceId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.bare(workspaceId ?? "") });
      toast.success("Campaign deleted");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to delete campaign")),
  });

  const duplicateMutation = useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return campaignsApi.duplicate(workspaceId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.bare(workspaceId ?? "") });
      toast.success("Campaign duplicated");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to duplicate campaign")),
  });

  const filteredCampaigns = campaigns.filter((campaign) => {
    const matchesSearch = campaign.name
      .toLowerCase()
      .includes(searchQuery.toLowerCase());
    const matchesStatus =
      statusFilter === "all" || campaign.status === statusFilter;
    const matchesType = typeFilter === "all" || campaign.campaign_type === typeFilter;
    return matchesSearch && matchesStatus && matchesType;
  });

  const getDeliveryRate = (campaign: Campaign) => {
    if (campaign.messages_sent === 0) return 0;
    return Math.round(
      (campaign.messages_delivered / campaign.messages_sent) * 100
    );
  };

  const getResponseRate = (campaign: Campaign) => {
    if (campaign.messages_sent === 0) return 0;
    return Math.round(
      (campaign.replies_received / campaign.messages_sent) * 100
    );
  };

  if (isPending) return <ResourceListLoading />;

  if (error) {
    return (
      <ResourceListError
        resourceName="campaigns"
        onRetry={() => queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.bare(workspaceId ?? "") })}
      />
    );
  }

  return (
    <ResourceListLayout
      header={
        <ResourceListHeader
          title="Campaigns"
          subtitle="Create and manage your outreach campaigns"
          action={
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button>
                  New Campaign
                  <ChevronDown className="ml-2 size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuItem asChild>
                  <Link href="/campaigns/sms/new" className="flex items-center cursor-pointer">
                    <MessageSquare className="mr-2 size-4" />
                    SMS Campaign
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link href="/campaigns/voice/new" className="flex items-center cursor-pointer">
                    <Phone className="mr-2 size-4" />
                    <div>
                      <div>Voice Campaign with SMS Fallback</div>
                      <div className="text-xs text-muted-foreground">AI calls with auto-text on failures</div>
                    </div>
                  </Link>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          }
        />
      }
      stats={
        <ResourceListStats
          stats={[
            { label: "Total Campaigns", value: campaigns.length },
            { label: "Active", value: campaigns.filter((c) => c.status === "running").length },
            { label: "Total Contacts", value: campaigns.reduce((sum, c) => sum + c.total_contacts, 0) },
            { label: "Total Responses", value: campaigns.reduce((sum, c) => sum + c.replies_received, 0) },
          ]}
        />
      }
      filterBar={
        <ResourceListSearch
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          placeholder="Search campaigns..."
          filters={
            <>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="draft">Draft</SelectItem>
                  <SelectItem value="scheduled">Scheduled</SelectItem>
                  <SelectItem value="running">Running</SelectItem>
                  <SelectItem value="paused">Paused</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                </SelectContent>
              </Select>
              <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="sms">SMS</SelectItem>
                  <SelectItem value="email">Email</SelectItem>
                  <SelectItem value="voice">Voice</SelectItem>
                  <SelectItem value="multi_channel">Multi-Channel</SelectItem>
                </SelectContent>
              </Select>
            </>
          }
        />
      }
      isEmpty={filteredCampaigns.length === 0}
      emptyState={
        <PageEmptyState
          icon={<MessageSquare className="size-12" />}
          title="No campaigns yet"
          description="Create your first campaign to start reaching your contacts"
        />
      }
      pagination={
        <ResourceListPagination
          filteredCount={filteredCampaigns.length}
          totalCount={campaigns.length}
          resourceName="campaigns"
        />
      }
    >
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Campaign</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Delivery</TableHead>
                <TableHead>Response</TableHead>
                <TableHead className="w-[50px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <AnimatePresence mode="popLayout">
                {filteredCampaigns.map((campaign, index) => {
                  const TypeIcon = typeIcons[campaign.campaign_type];
                  const progress =
                    campaign.total_contacts > 0
                      ? (campaign.messages_sent / campaign.total_contacts) * 100
                      : 0;

                  return (
                    <motion.tr
                      key={campaign.id}
                      layout
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{
                        type: "spring",
                        stiffness: 300,
                        damping: 24,
                        delay: index * 0.05,
                      }}
                      className="group cursor-pointer hover:bg-muted/50"
                    >
                      <TableCell>
                        <Link
                          href={`/campaigns/${campaign.id}`}
                          className="block"
                        >
                          <div className="font-medium">{campaign.name}</div>
                          <div className="text-sm text-muted-foreground line-clamp-1">
                            {campaign.description}
                          </div>
                        </Link>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <TypeIcon className="size-4 text-muted-foreground" />
                          <span className="capitalize">
                            {campaign.campaign_type.replace("_", " ")}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={campaignStatusColors[campaign.status]}
                        >
                          {campaign.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="space-y-1">
                          <Progress value={progress} className="h-2 w-24" />
                          <div className="text-xs text-muted-foreground">
                            {formatNumber(campaign.messages_sent)} /{" "}
                            {formatNumber(campaign.total_contacts)}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">
                          {getDeliveryRate(campaign)}%
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">
                          {getResponseRate(campaign)}%
                        </div>
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="opacity-0 group-hover:opacity-100"
                            >
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {campaign.status === "running" ? (
                              <DropdownMenuItem onSelect={() => pauseMutation.mutate(campaign.id)}>
                                <Pause className="mr-2 size-4" />
                                Pause
                              </DropdownMenuItem>
                            ) : campaign.status === "paused" ||
                              campaign.status === "draft" ? (
                              <DropdownMenuItem onSelect={() => startMutation.mutate(campaign.id)}>
                                <Play className="mr-2 size-4" />
                                {campaign.status === "draft"
                                  ? "Start"
                                  : "Resume"}
                              </DropdownMenuItem>
                            ) : null}
                            <DropdownMenuItem onSelect={() => duplicateMutation.mutate(campaign.id)}>
                              <Copy className="mr-2 size-4" />
                              Duplicate
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem variant="destructive" onSelect={() => deleteMutation.mutate(campaign.id)}>
                              <Trash2 className="mr-2 size-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </motion.tr>
                  );
                })}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </ResourceListLayout>
  );
}
