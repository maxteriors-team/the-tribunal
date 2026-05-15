"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

interface InfoRowProps {
  icon: React.ReactNode;
  label: string;
  value?: string | null;
  onClick?: () => void;
}

export function InfoRow({ icon, label, value, onClick }: InfoRowProps) {
  if (!value) return null;

  const content = (
    <div className="flex items-start gap-3 py-2 w-full">
      <div className="h-8 w-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
        {icon}
      </div>
      <div className="flex-1 min-w-0 text-left">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-medium truncate">{value}</p>
      </div>
      {onClick && (
        <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 mt-2" />
      )}
    </div>
  );

  if (onClick) {
    return (
      <Button
        variant="ghost"
        onClick={onClick}
        className="w-full justify-start h-auto py-0 px-2 -mx-2 font-normal hover:bg-accent/50"
      >
        {content}
      </Button>
    );
  }

  return <div className="px-2 -mx-2">{content}</div>;
}
