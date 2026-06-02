"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  FileText,
  Video,
  CheckSquare,
  FileSpreadsheet,
  PlayCircle,
  Zap,
  Users,
  BookOpen,
  GraduationCap,
  MoreHorizontal,
  Edit,
  Trash2,
  Mail,
  Download,
  ExternalLink,
  MessageSquare,
  DollarSign,
  CircleHelp,
  Calculator,
  FileEdit,
  Clapperboard,
} from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { AppSidebar } from "@/components/layout/app-sidebar";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageEmptyState } from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { leadMagnetsApi, CreateLeadMagnetRequest } from "@/lib/api/lead-magnets";
import { queryKeys } from "@/lib/query-keys";
import type { LeadMagnet, LeadMagnetType, DeliveryMethod } from "@/types";

const magnetTypeIcons: Record<LeadMagnetType, React.ReactNode> = {
  pdf: <FileText className="size-4" />,
  video: <Video className="size-4" />,
  checklist: <CheckSquare className="size-4" />,
  template: <FileSpreadsheet className="size-4" />,
  webinar: <PlayCircle className="size-4" />,
  free_trial: <Zap className="size-4" />,
  consultation: <Users className="size-4" />,
  ebook: <BookOpen className="size-4" />,
  mini_course: <GraduationCap className="size-4" />,
  quiz: <CircleHelp className="size-4" />,
  calculator: <Calculator className="size-4" />,
  rich_text: <FileEdit className="size-4" />,
  video_course: <Clapperboard className="size-4" />,
};

const magnetTypeLabels: Record<LeadMagnetType, string> = {
  pdf: "PDF Guide",
  video: "Video",
  checklist: "Checklist",
  template: "Template",
  webinar: "Webinar",
  free_trial: "Free Trial",
  consultation: "Consultation",
  ebook: "eBook",
  mini_course: "Mini Course",
  quiz: "Quiz",
  calculator: "Calculator",
  rich_text: "Rich Text",
  video_course: "Video Course",
};

const deliveryMethodIcons: Record<DeliveryMethod, React.ReactNode> = {
  email: <Mail className="size-3" />,
  download: <Download className="size-3" />,
  redirect: <ExternalLink className="size-3" />,
  sms: <MessageSquare className="size-3" />,
};

export default function LeadMagnetsPage() {
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [editingMagnet, setEditingMagnet] = useState<LeadMagnet | null>(null);
  const [deleteMagnetId, setDeleteMagnetId] = useState<string | null>(null);

  const [formData, setFormData] = useState<CreateLeadMagnetRequest>({
    name: "",
    description: "",
    magnet_type: "pdf",
    delivery_method: "email",
    content_url: "",
    estimated_value: 0,
    is_active: true,
  });

  const { data, isPending } = useQuery({
    queryKey: queryKeys.leadMagnets.all(workspaceId ?? ""),
    queryFn: () => leadMagnetsApi.list(workspaceId!),
    enabled: !!workspaceId,
  });

  const createMutation = useMutation({
    mutationFn: (data: CreateLeadMagnetRequest) =>
      leadMagnetsApi.create(workspaceId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.leadMagnets.all(workspaceId ?? "") });
      setShowCreateDialog(false);
      resetForm();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<CreateLeadMagnetRequest> }) =>
      leadMagnetsApi.update(workspaceId!, id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.leadMagnets.all(workspaceId ?? "") });
      setEditingMagnet(null);
      resetForm();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => leadMagnetsApi.delete(workspaceId!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.leadMagnets.all(workspaceId ?? "") });
      setDeleteMagnetId(null);
    },
  });

  const resetForm = () => {
    setFormData({
      name: "",
      description: "",
      magnet_type: "pdf",
      delivery_method: "email",
      content_url: "",
      estimated_value: 0,
      is_active: true,
    });
  };

  const openEditDialog = (magnet: LeadMagnet) => {
    setEditingMagnet(magnet);
    setFormData({
      name: magnet.name,
      description: magnet.description || "",
      magnet_type: magnet.magnet_type,
      delivery_method: magnet.delivery_method,
      content_url: magnet.content_url,
      estimated_value: magnet.estimated_value || 0,
      is_active: magnet.is_active,
    });
  };

  const handleSubmit = () => {
    if (editingMagnet) {
      updateMutation.mutate({ id: editingMagnet.id, data: formData });
    } else {
      createMutation.mutate(formData);
    }
  };

  const leadMagnets = data?.items || [];
  const activeLeadMagnets = leadMagnets.filter((lm) => lm.is_active);
  const totalDownloads = leadMagnets.reduce((sum, lm) => sum + lm.download_count, 0);

  return (
    <AppSidebar>
      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Lead Magnets</h1>
            <p className="text-muted-foreground">
              Create freebies to attach as bonuses to your offers
            </p>
          </div>
          <Button onClick={() => setShowCreateDialog(true)}>
            <Plus className="size-4 mr-2" />
            Create Lead Magnet
          </Button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Lead Magnets
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{leadMagnets.length}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Active
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold text-success">
                {activeLeadMagnets.length}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Downloads
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold text-info">{totalDownloads}</p>
            </CardContent>
          </Card>
        </div>

        {/* Lead Magnets List */}
        {isPending ? (
          <div className="grid grid-cols-2 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-40 w-full" />
            ))}
          </div>
        ) : leadMagnets.length === 0 ? (
          <Card>
            <CardContent className="py-4">
              <PageEmptyState
                title="No lead magnets yet"
                description="Create your first lead magnet to attach as a bonus to offers"
                icon={<FileText className="size-12" />}
                action={
                  <Button onClick={() => setShowCreateDialog(true)}>
                    <Plus className="size-4 mr-2" />
                    Create Your First Lead Magnet
                  </Button>
                }
              />
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {leadMagnets.map((magnet) => (
              <motion.div
                key={magnet.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <Card className={!magnet.is_active ? "opacity-60" : ""}>
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-4">
                        <div className="size-12 rounded-full bg-gradient-to-br from-info/20 to-primary/5 flex items-center justify-center text-info">
                          {magnetTypeIcons[magnet.magnet_type]}
                        </div>
                        <div>
                          <div className="flex items-center gap-2 flex-wrap">
                            <h3 className="font-semibold">{magnet.name}</h3>
                            <Badge
                              variant="secondary"
                              className="bg-info/10 text-info"
                            >
                              {magnetTypeLabels[magnet.magnet_type]}
                            </Badge>
                            {!magnet.is_active && (
                              <Badge variant="secondary">Inactive</Badge>
                            )}
                          </div>
                          {magnet.description && (
                            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                              {magnet.description}
                            </p>
                          )}
                          <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
                            <div className="flex items-center gap-1">
                              {deliveryMethodIcons[magnet.delivery_method]}
                              <span className="capitalize">
                                {magnet.delivery_method.replace("_", " ")}
                              </span>
                            </div>
                            {magnet.estimated_value && magnet.estimated_value > 0 && (
                              <div className="flex items-center gap-1 text-success">
                                <DollarSign className="size-3" />
                                {magnet.estimated_value} value
                              </div>
                            )}
                            <span>{magnet.download_count} downloads</span>
                          </div>
                        </div>
                      </div>

                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" aria-label="Lead magnet actions">
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => openEditDialog(magnet)}>
                            <Edit className="size-4 mr-2" />
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive"
                            onClick={() => setDeleteMagnetId(magnet.id)}
                          >
                            <Trash2 className="size-4 mr-2" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Create/Edit Dialog */}
      <Dialog
        open={showCreateDialog || !!editingMagnet}
        onOpenChange={(open) => {
          if (!open) {
            setShowCreateDialog(false);
            setEditingMagnet(null);
            resetForm();
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {editingMagnet ? "Edit Lead Magnet" : "Create Lead Magnet"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                placeholder="e.g., Free ROI Calculator"
                value={formData.name}
                onChange={(e) =>
                  setFormData({ ...formData, name: e.target.value })
                }
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Type</Label>
                <Select
                  value={formData.magnet_type}
                  onValueChange={(v) =>
                    setFormData({ ...formData, magnet_type: v as LeadMagnetType })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(magnetTypeLabels).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        <div className="flex items-center gap-2">
                          {magnetTypeIcons[value as LeadMagnetType]}
                          {label}
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Delivery</Label>
                <Select
                  value={formData.delivery_method}
                  onValueChange={(v) =>
                    setFormData({ ...formData, delivery_method: v as DeliveryMethod })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="email">Email</SelectItem>
                    <SelectItem value="download">Direct Download</SelectItem>
                    <SelectItem value="redirect">Redirect URL</SelectItem>
                    <SelectItem value="sms">SMS Link</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="content_url">Content URL</Label>
              <Input
                id="content_url"
                placeholder="https://example.com/download/guide.pdf"
                value={formData.content_url}
                onChange={(e) =>
                  setFormData({ ...formData, content_url: e.target.value })
                }
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="estimated_value">Perceived Value ($)</Label>
              <Input
                id="estimated_value"
                type="number"
                min="0"
                placeholder="e.g., 97"
                value={formData.estimated_value || ""}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    estimated_value: parseFloat(e.target.value) || 0,
                  })
                }
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                placeholder="Brief description of what they'll get..."
                value={formData.description}
                onChange={(e) =>
                  setFormData({ ...formData, description: e.target.value })
                }
                rows={2}
              />
            </div>

            <Button
              onClick={handleSubmit}
              disabled={
                !formData.name ||
                !formData.content_url ||
                createMutation.isPending ||
                updateMutation.isPending
              }
              className="w-full"
            >
              {createMutation.isPending || updateMutation.isPending
                ? "Saving..."
                : editingMagnet
                ? "Update Lead Magnet"
                : "Create Lead Magnet"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteMagnetId}
        onOpenChange={() => setDeleteMagnetId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Lead Magnet</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this lead magnet? This action cannot
              be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteMagnetId && deleteMutation.mutate(deleteMagnetId)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppSidebar>
  );
}
