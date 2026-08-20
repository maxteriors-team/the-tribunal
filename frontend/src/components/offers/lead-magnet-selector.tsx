"use client";

import {
  FileText,
  Video,
  CheckSquare,
  FileSpreadsheet,
  PlayCircle,
  Zap,
  Users,
  BookOpen,
  GraduationCap,
  Check,
  Plus,
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

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
import { Textarea } from "@/components/ui/textarea";
import type { LeadMagnet, LeadMagnetType, DeliveryMethod } from "@/types";

interface LeadMagnetSelectorProps {
  leadMagnets: LeadMagnet[];
  selectedIds: string[];
  onSelect: (leadMagnetIds: string[]) => void;
  onCreateLeadMagnet?: (leadMagnet: Partial<LeadMagnet>) => Promise<void>;
  multiSelect?: boolean;
}

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

export function LeadMagnetSelector({
  leadMagnets,
  selectedIds,
  onSelect,
  onCreateLeadMagnet,
  multiSelect = true,
}: LeadMagnetSelectorProps) {
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newMagnet, setNewMagnet] = useState<Partial<LeadMagnet>>({
    name: "",
    description: "",
    magnet_type: "pdf",
    delivery_method: "email",
    content_url: "",
    estimated_value: 0,
    is_active: true,
  });
  const [isCreating, setIsCreating] = useState(false);

  const handleToggle = (magnetId: string) => {
    if (multiSelect) {
      if (selectedIds.includes(magnetId)) {
        onSelect(selectedIds.filter((id) => id !== magnetId));
      } else {
        onSelect([...selectedIds, magnetId]);
      }
    } else {
      onSelect(selectedIds.includes(magnetId) ? [] : [magnetId]);
    }
  };

  const handleCreate = async () => {
    if (!onCreateLeadMagnet || !newMagnet.name || !newMagnet.content_url) return;
    setIsCreating(true);
    try {
      await onCreateLeadMagnet(newMagnet);
      setShowCreateDialog(false);
      setNewMagnet({
        name: "",
        description: "",
        magnet_type: "pdf",
        delivery_method: "email",
        content_url: "",
        estimated_value: 0,
        is_active: true,
      });
    } finally {
      setIsCreating(false);
    }
  };

  const activeLeadMagnets = leadMagnets.filter((lm) => lm.is_active);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <FileText className="size-4" />
          <span>Add bonus lead magnets to your offer ({activeLeadMagnets.length} available)</span>
        </div>

        {onCreateLeadMagnet && (
          <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm">
                <Plus className="size-4 mr-1" />
                Create Lead Magnet
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>Create New Lead Magnet</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="magnet-name">Name</Label>
                  <Input
                    id="magnet-name"
                    placeholder="e.g., Free ROI Calculator"
                    value={newMagnet.name}
                    onChange={(e) => setNewMagnet({ ...newMagnet, name: e.target.value })}
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="offer-lead-magnet-type">Type</Label>
                    <Select
                      value={newMagnet.magnet_type}
                      onValueChange={(v) =>
                        setNewMagnet({
                          ...newMagnet,
                          magnet_type: v as LeadMagnetType,
                        })
                      }
                    >
                      <SelectTrigger id="offer-lead-magnet-type">
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
                    <Label htmlFor="offer-lead-magnet-delivery">Delivery</Label>
                    <Select
                      value={newMagnet.delivery_method}
                      onValueChange={(v) =>
                        setNewMagnet({
                          ...newMagnet,
                          delivery_method: v as DeliveryMethod,
                        })
                      }
                    >
                      <SelectTrigger id="offer-lead-magnet-delivery">
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
                  <Label htmlFor="content-url">Content URL</Label>
                  <Input
                    id="content-url"
                    placeholder="https://example.com/download/guide.pdf"
                    value={newMagnet.content_url}
                    onChange={(e) => setNewMagnet({ ...newMagnet, content_url: e.target.value })}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="estimated-value">Perceived Value ($)</Label>
                  <Input
                    id="estimated-value"
                    type="number"
                    min="0"
                    placeholder="e.g., 97"
                    value={newMagnet.estimated_value || ""}
                    onChange={(e) =>
                      setNewMagnet({
                        ...newMagnet,
                        estimated_value: parseFloat(e.target.value) || 0,
                      })
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    The perceived value shown in your offer stack
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="magnet-description">Description</Label>
                  <Textarea
                    id="magnet-description"
                    placeholder="Brief description of what they'll get..."
                    value={newMagnet.description}
                    onChange={(e) => setNewMagnet({ ...newMagnet, description: e.target.value })}
                    rows={2}
                  />
                </div>

                <Button
                  onClick={handleCreate}
                  disabled={!newMagnet.name || !newMagnet.content_url || isCreating}
                  className="w-full"
                >
                  {isCreating ? "Creating..." : "Create Lead Magnet"}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )}
      </div>

      <ScrollArea className="h-[300px]">
        <div className="space-y-2 pr-4">
          {activeLeadMagnets.map((magnet) => {
            const isSelected = selectedIds.includes(magnet.id);

            return (
              <motion.div
                key={magnet.id}
                whileHover={{ scale: 1.01 }}
                whileTap={{ scale: 0.99 }}
                onClick={() => handleToggle(magnet.id)}
                className={`relative p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  isSelected
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <div className="flex items-start gap-3">
                  {multiSelect && (
                    <Checkbox
                      checked={isSelected}
                      className="mt-1"
                      onClick={(e) => e.stopPropagation()}
                      onCheckedChange={() => handleToggle(magnet.id)}
                    />
                  )}

                  {!multiSelect && isSelected && (
                    <div className="absolute top-3 right-3">
                      <div className="size-5 rounded-full bg-primary flex items-center justify-center">
                        <Check className="size-3 text-primary-foreground" />
                      </div>
                    </div>
                  )}

                  <div className="size-10 rounded-full bg-gradient-to-br from-info/20 to-primary/5 flex items-center justify-center text-info">
                    {magnetTypeIcons[magnet.magnet_type]}
                  </div>

                  <div className="flex-1 min-w-0 pr-6">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium">{magnet.name}</span>
                      <Badge variant="secondary" className="bg-info/10 text-info">
                        {magnetTypeLabels[magnet.magnet_type]}
                      </Badge>
                      {magnet.estimated_value && magnet.estimated_value > 0 && (
                        <Badge variant="outline" className="text-success border-success/20">
                          <DollarSign className="size-3 mr-0.5" />
                          {magnet.estimated_value} value
                        </Badge>
                      )}
                    </div>

                    {magnet.description && (
                      <p className="text-sm text-muted-foreground mt-1 line-clamp-1">
                        {magnet.description}
                      </p>
                    )}

                    <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                      <div className="flex items-center gap-1">
                        {deliveryMethodIcons[magnet.delivery_method]}
                        <span className="capitalize">
                          {magnet.delivery_method.replace("_", " ")}
                        </span>
                      </div>
                      {magnet.download_count > 0 && <span>{magnet.download_count} downloads</span>}
                    </div>
                  </div>
                </div>
              </motion.div>
            );
          })}

          {activeLeadMagnets.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <FileText className="size-12 mb-2 opacity-50" />
              <p>No lead magnets available</p>
              {onCreateLeadMagnet && (
                <Button variant="link" onClick={() => setShowCreateDialog(true)} className="mt-1">
                  Create your first lead magnet
                </Button>
              )}
            </div>
          )}
        </div>
      </ScrollArea>

      {selectedIds.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-3 bg-info/10 rounded-lg border border-info/20 text-sm"
        >
          <p className="text-info">
            {selectedIds.length} bonus{selectedIds.length > 1 ? "es" : ""} selected
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            These will be shown as bonus items in your offer value stack
          </p>
        </motion.div>
      )}
    </div>
  );
}
