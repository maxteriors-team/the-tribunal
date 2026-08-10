"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { settingsApi } from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

const UNASSIGNED_VALUE = "unassigned";

interface TeamMemberPickerProps {
  workspaceId: string;
  value: number | null;
  onValueChange: (userId: number | null) => void;
  label?: string;
  disabled?: boolean;
  allowUnassigned?: boolean;
  className?: string;
  triggerId?: string;
}

export function TeamMemberPicker({
  workspaceId,
  value,
  onValueChange,
  label,
  disabled = false,
  allowUnassigned = true,
  className,
  triggerId,
}: TeamMemberPickerProps) {
  const membersQuery = useQuery({
    queryKey: queryKeys.settings.activeTeam(workspaceId),
    queryFn: () => settingsApi.getActiveTeamMembers(workspaceId),
    enabled: Boolean(workspaceId),
  });

  const select = (
    <Select
      value={value === null ? UNASSIGNED_VALUE : String(value)}
      onValueChange={(nextValue) =>
        onValueChange(nextValue === UNASSIGNED_VALUE ? null : Number(nextValue))
      }
      disabled={disabled || membersQuery.isLoading || membersQuery.isError}
    >
      <SelectTrigger id={triggerId} className="w-full">
        <SelectValue
          placeholder={membersQuery.isLoading ? "Loading team…" : "Choose a team member"}
        />
      </SelectTrigger>
      <SelectContent>
        {allowUnassigned && (
          <SelectItem value={UNASSIGNED_VALUE}>
            <span className="text-muted-foreground">Unassigned</span>
          </SelectItem>
        )}
        {membersQuery.data?.map((member) => (
          <SelectItem key={member.id} value={String(member.id)}>
            <span className="flex min-w-0 flex-col py-0.5">
              <span className="truncate font-medium">{member.full_name || member.email}</span>
              <span className="truncate text-xs text-muted-foreground">
                {member.email} · {member.role.replaceAll("_", " ")}
              </span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  return (
    <div className={cn("space-y-2", className)}>
      {label ? <Label htmlFor={triggerId}>{label}</Label> : null}
      {membersQuery.isLoading ? (
        <div className="flex h-9 items-center gap-2 rounded-md border px-3 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading active team…
        </div>
      ) : (
        select
      )}
      {membersQuery.isError ? (
        <div className="flex items-center justify-between gap-3 text-sm text-destructive">
          <span className="flex items-center gap-1.5">
            <AlertCircle className="size-4" />
            Team members could not be loaded.
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1"
            onClick={() => void membersQuery.refetch()}
          >
            <RefreshCw className="size-3.5" />
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  );
}
