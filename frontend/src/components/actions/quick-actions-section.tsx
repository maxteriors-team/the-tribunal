"use client";

import {
  Receipt,
  Handshake,
  CalendarPlus,
  Megaphone,
  Forward,
  Star,
  Download,
  Archive,
  MousePointerClick,
} from "lucide-react";
import { motion } from "motion/react";
import { type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useContactStore } from "@/lib/contact-store";
import { cn } from "@/lib/utils";

interface QuickAction {
  id: string;
  label: string;
  description: string;
  icon: ReactNode;
  variant?: "default" | "outline" | "destructive";
  action: (contactId: number) => void;
}

const quickActions: QuickAction[] = [
  {
    id: "send_invoice",
    label: "Send Invoice",
    description: "Create and send an invoice",
    icon: <Receipt className="h-4 w-4" />,
    variant: "default",
    action: (contactId) => {
      toast.success("Invoice dialog opened", {
        description: `Creating invoice for contact #${contactId}`,
      });
    },
  },
  {
    id: "create_deal",
    label: "Create Deal",
    description: "Start a new opportunity",
    icon: <Handshake className="h-4 w-4" />,
    variant: "default",
    action: (contactId) => {
      toast.success("Deal created", {
        description: `New deal started for contact #${contactId}`,
      });
    },
  },
  {
    id: "schedule_appointment",
    label: "Schedule",
    description: "Book an appointment",
    icon: <CalendarPlus className="h-4 w-4" />,
    variant: "outline",
    action: (contactId) => {
      toast.success("Scheduler opened", {
        description: `Scheduling for contact #${contactId}`,
      });
    },
  },
  {
    id: "add_to_campaign",
    label: "Add to Campaign",
    description: "Add to marketing campaign",
    icon: <Megaphone className="h-4 w-4" />,
    variant: "outline",
    action: (contactId) => {
      toast.success("Campaign selector opened", {
        description: `Selecting campaign for contact #${contactId}`,
      });
    },
  },
  {
    id: "send_followup",
    label: "Send Follow-up",
    description: "Trigger follow-up sequence",
    icon: <Forward className="h-4 w-4" />,
    variant: "outline",
    action: (contactId) => {
      toast.success("Follow-up sent", {
        description: `Follow-up sequence started for contact #${contactId}`,
      });
    },
  },
  {
    id: "mark_vip",
    label: "Mark VIP",
    description: "Add VIP status to contact",
    icon: <Star className="h-4 w-4" />,
    variant: "outline",
    action: (contactId) => {
      toast.success("VIP status added", {
        description: `Contact #${contactId} marked as VIP`,
      });
    },
  },
  {
    id: "export_contact",
    label: "Export",
    description: "Download contact data",
    icon: <Download className="h-4 w-4" />,
    variant: "outline",
    action: (contactId) => {
      toast.success("Export started", {
        description: `Exporting data for contact #${contactId}`,
      });
    },
  },
  {
    id: "archive_contact",
    label: "Archive",
    description: "Archive this contact",
    icon: <Archive className="h-4 w-4" />,
    variant: "destructive",
    action: (contactId) => {
      toast.warning("Contact archived", {
        description: `Contact #${contactId} has been archived`,
      });
    },
  },
];

interface QuickActionButtonProps {
  action: QuickAction;
  onClick: () => void;
  disabled?: boolean;
}

function QuickActionButton({ action, onClick, disabled }: QuickActionButtonProps) {
  return (
    <motion.div
      whileHover={{ scale: disabled ? 1 : 1.02 }}
      whileTap={{ scale: disabled ? 1 : 0.98 }}
    >
      <Button
        variant={action.variant || "outline"}
        size="sm"
        className={cn(
          "w-full h-auto py-3 flex flex-col items-center gap-1.5 transition-all",
          action.variant === "destructive" && "hover:bg-destructive/90"
        )}
        onClick={onClick}
        disabled={disabled}
      >
        {action.icon}
        <span className="text-xs font-medium">{action.label}</span>
      </Button>
    </motion.div>
  );
}

export function QuickActionsSection() {
  const { selectedContact } = useContactStore();

  const handleAction = (action: QuickAction) => {
    if (!selectedContact) return;
    action.action(selectedContact.id);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <MousePointerClick className="h-4 w-4 text-success" />
        <h3 className="text-sm font-semibold">Quick Actions</h3>
      </div>

      <p className="text-xs text-muted-foreground">
        One-click actions to quickly manage this contact.
      </p>

      <div className="grid grid-cols-2 gap-2">
        {quickActions.map((action) => (
          <QuickActionButton
            key={action.id}
            action={action}
            onClick={() => handleAction(action)}
            disabled={!selectedContact}
          />
        ))}
      </div>
    </div>
  );
}
