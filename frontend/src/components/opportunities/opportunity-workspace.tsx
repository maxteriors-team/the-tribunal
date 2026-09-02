"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarCheck, MessageSquareText, NotebookPen, PhoneCall } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ConversationFeed } from "@/components/conversation/conversation-feed";
import { OpportunityFollowups } from "@/components/opportunities/opportunity-followups";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ContactPicker } from "@/components/ui/contact-combobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TeamMemberPicker } from "@/components/workspaces/team-member-picker";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useContact } from "@/hooks/useContacts";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { formatDate, formatDateTime } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type {
  Opportunity,
  OpportunityActivity as OpportunityActivityRecord,
  PipelineStage,
} from "@/types";

interface OpportunityWorkspaceProps {
  opportunityId: string;
}

type WorkspaceTab = "notes" | "sms";
type OpportunityUpdate = Parameters<typeof opportunitiesApi.update>[2];

type DealUpdate = {
  input: OpportunityUpdate;
  successMessage: (updated: Opportunity) => string;
  errorMessage: string;
};

const CALL_OUTCOME_LABELS: Record<string, string> = {
  no_answer: "No answer",
  busy: "Busy",
  rejected: "Rejected",
  voicemail: "Voicemail",
  completed: "Completed",
  appointment_booked: "Appointment booked",
  lead_qualified: "Lead qualified",
  failed: "Failed",
};

const ACTIVITY_LABELS: Record<string, string> = {
  note: "Note",
  update: "Update",
  call: "Call",
  task_created: "Task created",
  task_completed: "Task completed",
  task_reopened: "Task reopened",
  stage_change: "Stage changed",
  installation_scheduled: "Installation scheduled",
};

function numericFilter(value: string | null): string | null {
  return value && /^\d+$/.test(value) && Number(value) > 0 ? value : null;
}

function installationDateFrom(activities: OpportunityActivityRecord[]): string | null {
  const latest = [...activities]
    .filter((activity) => activity.activity_type === "installation_scheduled")
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  return latest?.new_value && /^\d{4}-\d{2}-\d{2}$/.test(latest.new_value)
    ? latest.new_value
    : null;
}

export function OpportunityWorkspace({ opportunityId }: OpportunityWorkspaceProps) {
  const workspaceId = useWorkspaceId();
  const { can } = useCapabilities();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<WorkspaceTab>(() =>
    searchParams.get("tab") === "sms" ? "sms" : "notes",
  );

  const detailKey = queryKeys.opportunities.detail(workspaceId ?? "", opportunityId);
  const opportunityQuery = useQuery({
    queryKey: detailKey,
    queryFn: () => opportunitiesApi.get(workspaceId!, opportunityId),
    enabled: !!workspaceId && !!opportunityId,
  });
  const pipelinesQuery = useQuery({
    queryKey: queryKeys.opportunities.pipelines(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.listPipelines(workspaceId!),
    enabled: !!workspaceId,
  });

  const opportunity = opportunityQuery.data;
  const contactId = opportunity
    ? (opportunity.primary_contact_id ?? opportunity.primary_contact?.id)
    : undefined;
  const contactQuery = useContact(workspaceId ?? "", contactId);
  const pipeline = pipelinesQuery.data?.find(
    (candidate) => candidate.id === opportunity?.pipeline_id,
  );
  const stages = useMemo<PipelineStage[]>(
    () => [...(pipeline?.stages ?? [])].sort((a, b) => a.order - b.order),
    [pipeline?.stages],
  );
  const contactFilter = numericFilter(searchParams.get("contact"));
  const ownerFilter = numericFilter(searchParams.get("owner"));
  const backParams = new URLSearchParams();
  if (contactFilter) backParams.set("contact", contactFilter);
  if (ownerFilter) backParams.set("owner", ownerFilter);
  const backHref = `/opportunities${backParams.size ? `?${backParams.toString()}` : ""}`;
  const canAssignOwners = can("pipeline:write");
  const canScheduleInstallation = can("pipeline:write_own") && can("jobs:write");

  const updateMutation = useMutation({
    mutationFn: ({ input }: DealUpdate) =>
      opportunitiesApi.update(workspaceId!, opportunityId, input),
    onSuccess: (updated, change) => {
      queryClient.setQueryData<Opportunity>(detailKey, (current) =>
        current ? { ...current, ...updated } : updated,
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId ?? ""),
      });
      toast.success(change.successMessage(updated));
    },
    onError: (error: unknown, change) =>
      toast.error(getApiErrorMessage(error, change.errorMessage)),
  });

  function changeTab(value: string) {
    const tab: WorkspaceTab = value === "sms" ? "sms" : "notes";
    setActiveTab(tab);
    const params = new URLSearchParams(backParams);
    if (tab === "sms") params.set("tab", "sms");
    router.replace(
      `/opportunities/${encodeURIComponent(opportunityId)}${params.size ? `?${params.toString()}` : ""}`,
      { scroll: false },
    );
  }

  if (!workspaceId || opportunityQuery.isPending) {
    return (
      <main className="min-h-full" aria-busy="true">
        <PageLoadingState message="Loading deal workspace…" />
      </main>
    );
  }

  if (opportunityQuery.isError || !opportunity) {
    return (
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <Button asChild variant="ghost" className="mb-4 -ml-3">
          <Link href={backHref}>
            <ArrowLeft className="size-4" aria-hidden />
            Back to pipeline
          </Link>
        </Button>
        <PageErrorState
          message="Couldn't load this deal."
          onRetry={() => void opportunityQuery.refetch()}
        />
      </main>
    );
  }

  const installationDate = installationDateFrom(opportunity.activities ?? []);

  return (
    <main className="min-h-full bg-muted/20">
      <div className="mx-auto w-full max-w-7xl space-y-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <header className="space-y-4 border-b pb-5">
          <Button asChild variant="ghost" size="sm" className="-ml-3">
            <Link href={backHref}>
              <ArrowLeft className="size-4" aria-hidden />
              Back to pipeline
            </Link>
          </Button>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="capitalize">
                  {opportunity.status}
                </Badge>
                <Badge variant="secondary">{opportunity.probability}% probability</Badge>
                {opportunity.source ? <Badge variant="outline">{opportunity.source}</Badge> : null}
              </div>
              <h1 className="text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
                {opportunity.name}
              </h1>
              <p className="text-sm text-muted-foreground">
                {opportunity.primary_contact?.full_name ?? "No customer linked"}
                {opportunity.amount != null
                  ? ` · ${formatCurrency(opportunity.amount, opportunity.currency)}`
                  : ""}
              </p>
            </div>
            <div className="shrink-0 text-sm text-muted-foreground sm:text-right">
              <p>Updated {formatDateTime(opportunity.updated_at)}</p>
              {opportunity.expected_close_date ? (
                <p>Expected close {formatDate(opportunity.expected_close_date)}</p>
              ) : null}
            </div>
          </div>
        </header>

        <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
          <section className="min-w-0" aria-labelledby="deal-workspace-heading">
            <h2 id="deal-workspace-heading" className="sr-only">
              Deal notes and messages
            </h2>
            <Tabs value={activeTab} onValueChange={changeTab}>
              <TabsList className="grid w-full grid-cols-2 sm:w-80" aria-label="Deal workspace">
                <TabsTrigger value="notes">
                  <NotebookPen className="size-4" aria-hidden />
                  Notes
                </TabsTrigger>
                <TabsTrigger value="sms">
                  <MessageSquareText className="size-4" aria-hidden />
                  SMS
                </TabsTrigger>
              </TabsList>

              <TabsContent value="notes" className="mt-4 space-y-4">
                <Card>
                  <CardContent className="pt-6">
                    <OpportunityFollowups
                      workspaceId={workspaceId}
                      opportunityId={opportunity.id}
                      tasks={opportunity.tasks ?? []}
                    />
                  </CardContent>
                </Card>
                <OpportunityActivity activities={opportunity.activities ?? []} />
              </TabsContent>

              <TabsContent value="sms" className="mt-4">
                <Card className="gap-0 overflow-hidden py-0">
                  <CardContent className="h-[calc(100svh-23rem)] min-h-[20rem] p-0 sm:h-[calc(100svh-17rem)] sm:min-h-[28rem] lg:max-h-[48rem]">
                    {!contactId ? (
                      <ConversationUnavailable
                        title="No customer linked"
                        message="Link a customer in Deal details before sending a text."
                      />
                    ) : contactQuery.isPending ? (
                      <div className="flex h-full items-center justify-center" role="status">
                        Loading customer conversation…
                      </div>
                    ) : contactQuery.isError || !contactQuery.data ? (
                      <ConversationUnavailable
                        title="Customer unavailable"
                        message="The linked customer could not be loaded. The deal is still safe to edit."
                        onRetry={() => void contactQuery.refetch()}
                      />
                    ) : !contactQuery.data.phone_number ? (
                      <ConversationUnavailable
                        title="No mobile number"
                        message="Add a phone number to the customer record before sending a text."
                        contactId={contactQuery.data.id}
                      />
                    ) : (
                      <ConversationFeed className="h-full" contact={contactQuery.data} />
                    )}
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </section>

          <aside className="space-y-4" aria-label="Deal details">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Deal details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <OpportunityCustomerEditor
                  key={`${opportunity.id}:${opportunity.primary_contact_id ?? "none"}`}
                  workspaceId={workspaceId}
                  opportunity={opportunity}
                  isSaving={updateMutation.isPending}
                  onOpenSms={() => changeTab("sms")}
                  onSave={(nextContactId) =>
                    updateMutation.mutate({
                      input: { primary_contact_id: nextContactId },
                      successMessage: (updated) =>
                        updated.primary_contact
                          ? `Customer changed to ${updated.primary_contact.full_name}`
                          : "Deal customer updated",
                      errorMessage: "Failed to update deal customer",
                    })
                  }
                />

                <div className="space-y-1.5">
                  <Label htmlFor="opportunity-workspace-stage">Stage</Label>
                  {pipelinesQuery.isError ? (
                    <div className="space-y-2 rounded-md border p-3 text-sm text-muted-foreground">
                      <p>Pipeline stages are unavailable.</p>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => void pipelinesQuery.refetch()}
                      >
                        Retry
                      </Button>
                    </div>
                  ) : (
                    <Select
                      value={opportunity.stage_id ?? undefined}
                      onValueChange={(stageId) => {
                        const stageName =
                          stages.find((stage) => stage.id === stageId)?.name ?? "stage";
                        updateMutation.mutate({
                          input: { stage_id: stageId },
                          successMessage: () => `Moved to ${stageName}`,
                          errorMessage: "Failed to move deal",
                        });
                      }}
                      disabled={
                        pipelinesQuery.isPending || updateMutation.isPending || !stages.length
                      }
                    >
                      <SelectTrigger id="opportunity-workspace-stage" className="w-full">
                        <SelectValue
                          placeholder={
                            pipelinesQuery.isPending ? "Loading stages…" : "Select a stage"
                          }
                        />
                      </SelectTrigger>
                      <SelectContent>
                        {stages.map((stage) => (
                          <SelectItem key={stage.id} value={stage.id}>
                            {stage.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>

                {canAssignOwners ? (
                  <TeamMemberPicker
                    workspaceId={workspaceId}
                    value={opportunity.assigned_user_id ?? null}
                    onValueChange={(assignedUserId) =>
                      updateMutation.mutate({
                        input: { assigned_user_id: assignedUserId },
                        successMessage: (updated) =>
                          updated.assignee
                            ? `Assigned to ${updated.assignee.full_name || updated.assignee.email}`
                            : "Deal is unassigned",
                        errorMessage: "Failed to update deal owner",
                      })
                    }
                    label="Owner"
                    triggerId="opportunity-workspace-owner"
                    disabled={updateMutation.isPending}
                  />
                ) : (
                  <DealFact
                    label="Owner"
                    value={
                      opportunity.assignee
                        ? opportunity.assignee.full_name || opportunity.assignee.email
                        : "Unassigned"
                    }
                  />
                )}

                <div className="grid grid-cols-2 gap-4 border-t pt-4">
                  <DealFact
                    label="Amount"
                    value={
                      opportunity.amount != null
                        ? formatCurrency(opportunity.amount, opportunity.currency)
                        : "Not set"
                    }
                  />
                  <DealFact label="Probability" value={`${opportunity.probability}%`} />
                  <DealFact
                    label="Expected close"
                    value={
                      opportunity.expected_close_date
                        ? formatDate(opportunity.expected_close_date)
                        : "Not set"
                    }
                  />
                  <DealFact label="Source" value={opportunity.source || "Not set"} />
                </div>

                {opportunity.description ? (
                  <div className="space-y-1 border-t pt-4">
                    <p className="text-sm font-medium">Description</p>
                    <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                      {opportunity.description}
                    </p>
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <InstallationDateControl
              key={installationDate ?? "unscheduled"}
              workspaceId={workspaceId}
              opportunityId={opportunity.id}
              currentDate={installationDate}
              canEdit={canScheduleInstallation}
            />
          </aside>
        </div>
      </div>
    </main>
  );
}

function OpportunityCustomerEditor({
  workspaceId,
  opportunity,
  isSaving,
  onOpenSms,
  onSave,
}: {
  workspaceId: string;
  opportunity: Opportunity;
  isSaving: boolean;
  onOpenSms: () => void;
  onSave: (contactId: number) => void;
}) {
  const persistedContactId = String(
    opportunity.primary_contact_id ?? opportunity.primary_contact?.id ?? "",
  );
  const [contactId, setContactId] = useState(persistedContactId);
  const isDirty = contactId !== persistedContactId;
  const hasPhone = Boolean(opportunity.primary_contact?.phone_number);

  return (
    <div className="space-y-1.5">
      <Label htmlFor="opportunity-workspace-customer">Customer</Label>
      <ContactPicker
        id="opportunity-workspace-customer"
        workspaceId={workspaceId}
        value={contactId}
        initialContact={opportunity.primary_contact}
        onChange={(nextContactId) => setContactId(nextContactId)}
        placeholder="Search customers to relink…"
        disabled={isSaving}
        required
        data-testid="opportunity-workspace-customer-picker"
      />
      <p className="text-xs text-muted-foreground">
        {opportunity.primary_contact
          ? opportunity.primary_contact.phone_number ||
            opportunity.primary_contact.email ||
            "No phone or email on file"
          : "Select a saved customer to link this deal."}
      </p>
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div className="flex items-center gap-2">
          {opportunity.primary_contact ? (
            <Button asChild variant="link" size="sm" className="h-auto px-0">
              <Link href={`/contacts/${opportunity.primary_contact.id}/details`}>
                View customer
              </Link>
            </Button>
          ) : null}
          {opportunity.primary_contact ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-auto px-2"
              onClick={onOpenSms}
              disabled={!hasPhone}
            >
              Open SMS
            </Button>
          ) : null}
        </div>
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

function InstallationDateControl({
  workspaceId,
  opportunityId,
  currentDate,
  canEdit,
}: {
  workspaceId: string;
  opportunityId: string;
  currentDate: string | null;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [installationDate, setInstallationDate] = useState(currentDate ?? "");

  const mutation = useMutation({
    mutationFn: () =>
      opportunitiesApi.setInstallationDate(workspaceId, opportunityId, {
        installation_date: installationDate,
      }),
    onSuccess: (result) => {
      setInstallationDate(result.installation_date);
      toast.success("Installation date saved");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId),
      });
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Failed to schedule installation")),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarCheck className="size-4" aria-hidden />
          Installation
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {canEdit ? (
          <>
            <div className="space-y-1.5">
              <Label htmlFor="opportunity-installation-date">Installation date</Label>
              <Input
                id="opportunity-installation-date"
                type="date"
                value={installationDate}
                onChange={(event) => setInstallationDate(event.target.value)}
                aria-describedby="opportunity-installation-help"
              />
              <p id="opportunity-installation-help" className="text-xs text-muted-foreground">
                Updates the linked job scheduled for this deal.
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              className="w-full"
              onClick={() => mutation.mutate()}
              disabled={!installationDate || installationDate === currentDate || mutation.isPending}
            >
              {mutation.isPending ? "Saving…" : "Save installation date"}
            </Button>
          </>
        ) : (
          <DealFact
            label="Scheduled date"
            value={
              currentDate ? formatDate(`${currentDate}T12:00:00`) : "No installation scheduled"
            }
          />
        )}
      </CardContent>
    </Card>
  );
}

function OpportunityActivity({ activities }: { activities: OpportunityActivityRecord[] }) {
  const sortedActivities = [...activities].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Activity</CardTitle>
      </CardHeader>
      <CardContent>
        {sortedActivities.length ? (
          <ol className="space-y-0">
            {sortedActivities.map((activity) => {
              const isCall = activity.activity_type === "call";
              const isInstallation = activity.activity_type === "installation_scheduled";
              return (
                <li
                  key={activity.id}
                  className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-3 border-b py-3 first:pt-0 last:border-0 last:pb-0"
                >
                  <span className="pt-0.5 text-muted-foreground">
                    {isCall ? (
                      <PhoneCall className="size-4" aria-hidden />
                    ) : isInstallation ? (
                      <CalendarCheck className="size-4" aria-hidden />
                    ) : (
                      <NotebookPen className="size-4" aria-hidden />
                    )}
                  </span>
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                      <p className="text-sm font-medium">
                        {ACTIVITY_LABELS[activity.activity_type] ??
                          activity.activity_type.replaceAll("_", " ")}
                        {isCall && activity.new_value
                          ? ` · ${CALL_OUTCOME_LABELS[activity.new_value] ?? activity.new_value}`
                          : ""}
                      </p>
                      <time
                        dateTime={activity.created_at}
                        className="text-xs text-muted-foreground"
                      >
                        {formatDateTime(activity.created_at)}
                      </time>
                    </div>
                    {activity.description ? (
                      <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">
                        {activity.description}
                      </p>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-sm text-muted-foreground">No deal activity yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function ConversationUnavailable({
  title,
  message,
  contactId,
  onRetry,
}: {
  title: string;
  message: string;
  contactId?: number;
  onRetry?: () => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <MessageSquareText className="size-8 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
      </div>
      {onRetry ? (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      ) : contactId ? (
        <Button asChild variant="outline" size="sm">
          <Link href={`/contacts/${contactId}/details`}>Open customer</Link>
        </Button>
      ) : null}
    </div>
  );
}

function DealFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="break-words text-sm">{value}</p>
    </div>
  );
}
