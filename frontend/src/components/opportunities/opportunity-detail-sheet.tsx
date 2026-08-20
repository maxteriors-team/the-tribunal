"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { OpportunityFollowups } from "@/components/opportunities/opportunity-followups";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ContactPicker } from "@/components/ui/contact-combobox";
import { Label } from "@/components/ui/label";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { TeamMemberPicker } from "@/components/workspaces/team-member-picker";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Opportunity, PipelineStage } from "@/types";

interface OpportunityDetailSheetProps {
  workspaceId: string;
  opportunityId: string | null;
  stages: PipelineStage[];
  canAssignOwners: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function OpportunityDetailSheet({
  workspaceId,
  opportunityId,
  stages,
  canAssignOwners,
  open,
  onOpenChange,
}: OpportunityDetailSheetProps) {
  const queryClient = useQueryClient();

  const {
    data: opportunity,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: queryKeys.opportunities.detail(workspaceId, opportunityId ?? ""),
    queryFn: () => opportunitiesApi.get(workspaceId, opportunityId!),
    enabled: open && !!workspaceId && !!opportunityId,
  });

  const moveMutation = useMutation({
    mutationFn: (stageId: string) =>
      opportunitiesApi.update(workspaceId, opportunityId!, { stage_id: stageId }),
    onSuccess: (updated) => {
      const stageName = stages.find((s) => s.id === updated.stage_id)?.name ?? "stage";
      toast.success(`Moved to ${stageName}`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId),
      });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to move opportunity")),
  });

  const customerMutation = useMutation({
    mutationFn: (contactId: number) =>
      opportunitiesApi.update(workspaceId, opportunityId!, {
        primary_contact_id: contactId,
      }),
    onSuccess: (updated) => {
      toast.success(
        updated.primary_contact
          ? `Customer changed to ${updated.primary_contact.full_name}`
          : "Opportunity customer updated",
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId),
      });
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to update opportunity customer")),
  });

  const ownerMutation = useMutation({
    mutationFn: (assignedUserId: number | null) =>
      opportunitiesApi.update(workspaceId, opportunityId!, {
        assigned_user_id: assignedUserId,
      }),
    onSuccess: (updated) => {
      toast.success(
        updated.assignee
          ? `Assigned to ${updated.assignee.full_name || updated.assignee.email}`
          : "Opportunity is unassigned",
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId),
      });
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to update opportunity owner")),
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{opportunity?.name ?? "Opportunity"}</SheetTitle>
          <SheetDescription>
            View and move this opportunity between pipeline stages.
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-6 px-4 pb-6">
          {isPending ? (
            <PageLoadingState message="Loading opportunity…" />
          ) : isError || !opportunity ? (
            <PageErrorState
              message="Couldn't load this opportunity."
              onRetry={() => void refetch()}
            />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="capitalize">
                  {opportunity.status}
                </Badge>
                <Badge variant="secondary">{opportunity.probability}% probability</Badge>
                {opportunity.source ? <Badge variant="outline">{opportunity.source}</Badge> : null}
              </div>

              <OpportunityCustomerEditor
                key={`${opportunity.id}:${opportunity.primary_contact_id ?? "none"}`}
                workspaceId={workspaceId}
                opportunity={opportunity}
                isSaving={customerMutation.isPending}
                onSave={(contactId) => customerMutation.mutate(contactId)}
              />

              <div className="space-y-1.5">
                <p className="text-sm font-medium">Stage</p>
                <Select
                  value={opportunity.stage_id ?? undefined}
                  onValueChange={(value) => moveMutation.mutate(value)}
                  disabled={moveMutation.isPending}
                >
                  <SelectTrigger className="w-full" data-testid="opportunity-stage-select">
                    <SelectValue placeholder="Select a stage" />
                  </SelectTrigger>
                  <SelectContent>
                    {stages.map((stage) => (
                      <SelectItem key={stage.id} value={stage.id}>
                        {stage.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {canAssignOwners ? (
                <div className="space-y-1.5">
                  <TeamMemberPicker
                    workspaceId={workspaceId}
                    value={opportunity.assigned_user_id ?? null}
                    onValueChange={(userId) => ownerMutation.mutate(userId)}
                    label="Owner"
                    triggerId="opportunity-detail-owner"
                    disabled={ownerMutation.isPending}
                  />
                  {opportunity.assignee ? (
                    <p className="text-xs text-muted-foreground">
                      Current: {opportunity.assignee.full_name || opportunity.assignee.email}
                      {opportunity.assignee.full_name ? ` · ${opportunity.assignee.email}` : ""}
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="space-y-1">
                  <p className="text-sm font-medium">Owner</p>
                  <p className="text-sm text-muted-foreground">
                    {opportunity.assignee
                      ? opportunity.assignee.full_name || opportunity.assignee.email
                      : "Unassigned"}
                  </p>
                </div>
              )}

              {opportunity.amount != null ? (
                <div className="space-y-1">
                  <p className="text-sm font-medium">Amount</p>
                  <p className="text-sm text-muted-foreground">
                    {formatCurrency(opportunity.amount, opportunity.currency)}
                  </p>
                </div>
              ) : null}

              {opportunity.description ? (
                <div className="space-y-1">
                  <p className="text-sm font-medium">Description</p>
                  <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                    {opportunity.description}
                  </p>
                </div>
              ) : null}

              <OpportunityFollowups
                workspaceId={workspaceId}
                opportunityId={opportunity.id}
                tasks={opportunity.tasks ?? []}
              />

              {opportunity.activities && opportunity.activities.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-sm font-medium">Activity</p>
                  <ul className="space-y-2">
                    {opportunity.activities.map((activity) => (
                      <li
                        key={activity.id}
                        className="rounded-md border p-2 text-xs text-muted-foreground"
                      >
                        <span className="font-medium text-foreground">
                          {activity.activity_type.replace("_", " ")}
                        </span>
                        {activity.description ? ` — ${activity.description}` : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function OpportunityCustomerEditor({
  workspaceId,
  opportunity,
  isSaving,
  onSave,
}: {
  workspaceId: string;
  opportunity: Opportunity;
  isSaving: boolean;
  onSave: (contactId: number) => void;
}) {
  const persistedContactId = String(
    opportunity.primary_contact_id ?? opportunity.primary_contact?.id ?? "",
  );
  const [contactId, setContactId] = useState(persistedContactId);
  const isDirty = contactId !== persistedContactId;

  return (
    <div className="space-y-1.5">
      <Label htmlFor="opportunity-detail-customer">Customer</Label>
      <ContactPicker
        id="opportunity-detail-customer"
        workspaceId={workspaceId}
        value={contactId}
        initialContact={opportunity.primary_contact}
        onChange={(nextContactId) => setContactId(nextContactId)}
        placeholder="Search customers to relink…"
        disabled={isSaving}
        required
        data-testid="opportunity-detail-customer-picker"
      />
      {contactId ? (
        <p className="text-xs text-muted-foreground">
          Required. Choose another saved customer to relink this opportunity.
        </p>
      ) : (
        <p className="text-xs text-destructive">Select a saved customer.</p>
      )}
      {opportunity.primary_contact ? (
        <p className="text-xs text-muted-foreground">
          {opportunity.primary_contact.phone_number ||
            opportunity.primary_contact.email ||
            "No phone or email on file"}
        </p>
      ) : null}
      <div className="flex items-center justify-between gap-2 pt-1">
        {opportunity.primary_contact ? (
          <Button asChild variant="link" size="sm" className="h-auto px-0">
            <Link href={`/contacts/${opportunity.primary_contact.id}/details`}>
              View customer record
            </Link>
          </Button>
        ) : (
          <span />
        )}
        <Button
          type="button"
          size="sm"
          onClick={() => onSave(Number(contactId))}
          disabled={!contactId || !isDirty || isSaving}
        >
          {isSaving ? "Saving…" : "Save customer"}
        </Button>
      </div>
    </div>
  );
}
