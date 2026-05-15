"use client";

import { AlertCircle } from "lucide-react";
import dynamic from "next/dynamic";

import { Alert, AlertDescription } from "@/components/ui/alert";

const VirtualContactSelector = dynamic(
  () => import("../virtual-contact-selector").then((m) => m.VirtualContactSelector),
  { ssr: false, loading: () => <div className="h-96 rounded-md border bg-muted/30 animate-pulse" /> },
);

interface ContactsStepProps {
  workspaceId: string;
  selectedIds: Set<number>;
  onSelectionChange: (ids: Set<number>) => void;
  error?: string;
}

export function ContactsStep({
  workspaceId,
  selectedIds,
  onSelectionChange,
  error,
}: ContactsStepProps) {
  return (
    <div className="space-y-4">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <VirtualContactSelector
        workspaceId={workspaceId}
        selectedIds={selectedIds}
        onSelectionChange={onSelectionChange}
      />
    </div>
  );
}
