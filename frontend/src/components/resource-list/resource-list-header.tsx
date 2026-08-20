import type { ReactNode } from "react";

interface ResourceListHeaderProps {
  title: string;
  subtitle: string;
  action: ReactNode;
}

export function ResourceListHeader({ title, subtitle, action }: ResourceListHeaderProps) {
  return (
    <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight gradient-heading">{title}</h1>
        <p className="text-muted-foreground">{subtitle}</p>
      </div>
      <div className="w-full min-w-0 sm:w-auto">{action}</div>
    </div>
  );
}
