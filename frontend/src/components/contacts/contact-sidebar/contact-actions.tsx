"use client";

import { Phone, Calendar, Edit2, Bot, Trash2, Loader2 } from "lucide-react";
import { type ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface QuickActionProps {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  variant?: "default" | "primary" | "destructive";
  loading?: boolean;
  disabled?: boolean;
}

function QuickAction({
  icon,
  label,
  onClick,
  variant = "default",
  loading = false,
  disabled = false,
}: QuickActionProps) {
  return (
    <Button
      variant={variant === "destructive" ? "destructive" : variant === "primary" ? "default" : "outline"}
      size="sm"
      className="flex-1"
      onClick={onClick}
      disabled={disabled || loading}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      <span className="ml-2">{label}</span>
    </Button>
  );
}

interface ContactActionsProps {
  hasPhoneNumber: boolean;
  aiEnabled: boolean;
  isCalling: boolean;
  isTogglingAi: boolean;
  onCall: () => void;
  onSchedule: () => void;
  onEdit: () => void;
  onToggleAi: () => void;
  onDelete: () => void;
}

export function ContactActions({
  hasPhoneNumber,
  aiEnabled,
  isCalling,
  isTogglingAi,
  onCall,
  onSchedule,
  onEdit,
  onToggleAi,
  onDelete,
}: ContactActionsProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground px-2">Quick Actions</h3>
      <div className="flex gap-2">
        <QuickAction
          icon={<Phone className="h-4 w-4" />}
          label="Call"
          onClick={onCall}
          variant="primary"
          loading={isCalling}
          disabled={!hasPhoneNumber}
        />
        <QuickAction
          icon={<Calendar className="h-4 w-4" />}
          label="Schedule"
          onClick={onSchedule}
        />
      </div>
      <div className="flex gap-2">
        <QuickAction
          icon={<Edit2 className="h-4 w-4" />}
          label="Edit"
          onClick={onEdit}
        />
        <QuickAction
          icon={<Bot className="h-4 w-4" />}
          label={aiEnabled ? "AI On" : "AI Off"}
          onClick={onToggleAi}
          loading={isTogglingAi}
          variant={aiEnabled ? "primary" : "default"}
        />
      </div>
      <div className="flex gap-2">
        <QuickAction
          icon={<Trash2 className="h-4 w-4" />}
          label="Delete"
          onClick={onDelete}
          variant="destructive"
        />
      </div>
    </div>
  );
}
