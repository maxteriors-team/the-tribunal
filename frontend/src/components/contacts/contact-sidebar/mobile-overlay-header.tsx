"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface MobileOverlayHeaderProps {
  onClose: () => void;
}

export function MobileOverlayHeader({ onClose }: MobileOverlayHeaderProps) {
  return (
    <div className="flex items-center justify-between p-4 border-b">
      <h3 className="font-semibold">Contact Details</h3>
      <Button
        size="icon"
        variant="ghost"
        className="h-8 w-8"
        onClick={onClose}
        aria-label="Close contact details"
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}
