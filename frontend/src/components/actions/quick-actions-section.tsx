"use client";

import { CalendarPlus, MousePointerClick, Receipt } from "lucide-react";
import { type ReactNode, useState } from "react";

import { ScheduleAppointmentDialog } from "@/components/contacts/schedule-appointment-dialog";
import { InvoiceCreateDialog } from "@/components/invoices/invoice-create-dialog";
import { Button } from "@/components/ui/button";
import { useContactStore } from "@/lib/contact-store";

type QuickActionId = "send_invoice" | "schedule_appointment";

interface QuickAction {
  id: QuickActionId;
  label: string;
  icon: ReactNode;
  variant: "default" | "outline";
}

const quickActions: QuickAction[] = [
  {
    id: "send_invoice",
    label: "Send Invoice",
    icon: <Receipt className="h-4 w-4" />,
    variant: "default",
  },
  {
    id: "schedule_appointment",
    label: "Schedule",
    icon: <CalendarPlus className="h-4 w-4" />,
    variant: "outline",
  },
];

interface QuickActionButtonProps {
  action: QuickAction;
  onClick: () => void;
  disabled?: boolean;
}

function QuickActionButton({ action, onClick, disabled }: QuickActionButtonProps) {
  return (
    <Button
      variant={action.variant}
      size="sm"
      className="h-auto min-h-14 w-full flex-col gap-1.5 py-3"
      onClick={onClick}
      disabled={disabled}
    >
      {action.icon}
      <span className="text-xs font-medium">{action.label}</span>
    </Button>
  );
}

export function QuickActionsSection() {
  const { selectedContact } = useContactStore();
  const [invoiceDialogOpen, setInvoiceDialogOpen] = useState(false);
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);

  const handleAction = (action: QuickAction) => {
    if (!selectedContact) return;
    if (action.id === "send_invoice") {
      setInvoiceDialogOpen(true);
    } else {
      setScheduleDialogOpen(true);
    }
  };

  return (
    <div className="space-y-3" data-testid="contact-quick-actions">
      <div className="flex items-center gap-2">
        <MousePointerClick className="h-4 w-4 text-success" />
        <h3 className="text-sm font-semibold">Quick Actions</h3>
      </div>

      <p className="text-xs text-muted-foreground">
        Create invoices and book appointments without leaving this conversation.
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

      {selectedContact && (
        <>
          <InvoiceCreateDialog
            open={invoiceDialogOpen}
            onOpenChange={setInvoiceDialogOpen}
            contactId={selectedContact.id}
          />
          <ScheduleAppointmentDialog
            contact={selectedContact}
            open={scheduleDialogOpen}
            onOpenChange={setScheduleDialogOpen}
          />
        </>
      )}
    </div>
  );
}
