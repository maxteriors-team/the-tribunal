"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Play, Plus, Repeat, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { HorizontalScroll } from "@/components/ui/horizontal-scroll";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { contactsApi } from "@/lib/api/contacts";
import { servicePlansApi } from "@/lib/api/service-plans";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { ServicePlan, ServicePlanType } from "@/types";

import { ServicePlanDialog } from "./service-plan-dialog";

const FREQUENCY_LABELS: Record<ServicePlan["frequency"], string> = {
  weekly: "Weekly",
  biweekly: "Every 2 weeks",
  monthly: "Monthly",
  quarterly: "Quarterly",
  yearly: "Yearly",
};

const PLAN_TYPE_LABELS: Record<ServicePlanType, string> = {
  lighting_care_plan: "Care Plan",
  christmas_lights: "Christmas Lights",
  maintenance: "Maintenance",
};

/** Filter tabs. `all` is the default view; the rest map to `?plan_type=`. */
const TABS: { value: "all" | ServicePlanType; label: string }[] = [
  { value: "all", label: "All plans" },
  { value: "lighting_care_plan", label: "Care Plans" },
  { value: "christmas_lights", label: "Christmas Lights" },
  { value: "maintenance", label: "Maintenance" },
];

function scheduleLabel(plan: ServicePlan): string {
  const base = FREQUENCY_LABELS[plan.frequency];
  if (plan.interval <= 1) return base;
  if (plan.frequency === "monthly") return `Every ${plan.interval} months`;
  return `${base} × ${plan.interval}`;
}

/**
 * A row in the list: usually one plan, but a Christmas signup is stored as an
 * install plan *plus* a takedown plan, and the operator thinks of that as one
 * client on one seasonal plan. Grouping them keeps the list honest about how
 * many clients signed up while still exposing each dispatchable plan's actions.
 */
interface PlanRow {
  key: string;
  primary: ServicePlan;
  plans: ServicePlan[];
}

function groupPlans(plans: ServicePlan[]): PlanRow[] {
  const rows: PlanRow[] = [];
  const christmasRows = new Map<string, PlanRow>();

  for (const plan of plans) {
    if (plan.plan_type !== "christmas_lights") {
      rows.push({ key: plan.id, primary: plan, plans: [plan] });
      continue;
    }
    // Group by the signup, falling back to the customer for hand-built plans.
    const groupKey = `${plan.contact_id}:${plan.source_quote_id ?? "manual"}`;
    const existing = christmasRows.get(groupKey);
    if (existing) {
      existing.plans.push(plan);
      continue;
    }
    const row: PlanRow = { key: groupKey, primary: plan, plans: [plan] };
    christmasRows.set(groupKey, row);
    rows.push(row);
  }

  for (const row of christmasRows.values()) {
    // Soonest first, so "next occurrence" shows the visit actually coming up.
    row.plans.sort((a, b) => a.next_run_at.localeCompare(b.next_run_at));
    row.primary = row.plans[0];
  }
  return rows;
}

/** Strips the shared prefix so a grouped row reads "Install · Takedown". */
function planPartLabel(plan: ServicePlan): string {
  const [, part] = plan.title.split(" — ");
  return part?.trim() || plan.title;
}

export function ServicePlansList() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ServicePlan | null>(null);
  const [planType, setPlanType] = useState<"all" | ServicePlanType>("all");

  const listParams = planType === "all" ? undefined : { plan_type: planType };
  const query = useQuery({
    queryKey: queryKeys.servicePlans.list(workspaceId ?? "", listParams),
    queryFn: () => servicePlansApi.list(workspaceId ?? "", listParams),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });

  const contactsQuery = useQuery({
    queryKey: queryKeys.contacts.allRecords(workspaceId ?? ""),
    queryFn: () => contactsApi.listAll(workspaceId ?? ""),
    enabled: Boolean(workspaceId),
  });

  const contactName = (id: number): string => {
    const c = contactsQuery.data?.find((x) => x.id === id);
    if (!c) return `Customer #${id}`;
    const name = [c.first_name, c.last_name].filter(Boolean).join(" ").trim();
    return name || c.email || `Customer #${id}`;
  };

  const invalidate = () => {
    if (!workspaceId) return;
    void queryClient.invalidateQueries({
      queryKey: queryKeys.servicePlans.all(workspaceId),
    });
  };

  const runMutation = useMutation({
    mutationFn: (id: string) => servicePlansApi.run(workspaceId ?? "", id),
    onSuccess: (result) => {
      toast.success(
        result.created > 0
          ? `Generated ${result.created} job${result.created > 1 ? "s" : ""}`
          : "Nothing due — cursor advanced",
      );
      invalidate();
      if (workspaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.jobs.all(workspaceId),
        });
      }
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to generate job")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => servicePlansApi.delete(workspaceId ?? "", id),
    onSuccess: () => {
      toast.success("Service plan deleted");
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to delete")),
  });

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const openEdit = (plan: ServicePlan) => {
    setEditing(plan);
    setDialogOpen(true);
  };

  const newButton = (
    <Button className="w-full sm:w-auto" onClick={openCreate} size="sm">
      <Plus className="mr-1.5 h-4 w-4" />
      New service plan
    </Button>
  );

  const busy = runMutation.isPending || deleteMutation.isPending;

  let body: React.ReactNode;
  if (!workspaceId || query.isLoading) {
    body = <PageLoadingState message="Loading service plans..." />;
  } else if (query.isError) {
    body = (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Failed to load service plans")}
        onRetry={() => void query.refetch()}
      />
    );
  } else {
    const rows = groupPlans(query.data?.items ?? []);
    if (rows.length === 0) {
      body = (
        <PageEmptyState
          icon={<Repeat className="size-8" />}
          title={
            planType === "all"
              ? "No service plans yet"
              : `No ${PLAN_TYPE_LABELS[planType].toLowerCase()} plans yet`
          }
          description="A plan is created automatically when a client approves a proposal with a Care Plan or Christmas lights — or add one by hand."
          action={newButton}
        />
      );
    } else {
      body = (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Plan</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Schedule</TableHead>
              <TableHead>Next occurrence</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const plan = row.primary;
              const grouped = row.plans.length > 1;
              const anyActive = row.plans.some((p) => p.is_active);
              return (
                <TableRow key={row.key} className={anyActive ? "" : "opacity-50"}>
                  <TableCell className="font-medium">
                    {grouped ? row.plans.map(planPartLabel).join(" · ") : plan.title}
                    <div className="text-xs text-muted-foreground">
                      {contactName(plan.contact_id)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-1">
                      <Badge variant="outline">{PLAN_TYPE_LABELS[plan.plan_type]}</Badge>
                      {plan.care_plan_tier ? (
                        <Badge variant="secondary" className="capitalize">
                          {plan.care_plan_tier}
                        </Badge>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{scheduleLabel(plan)}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(plan.next_run_at, {
                      pattern: "MMM d, yyyy · h:mm a",
                    })}
                    {grouped ? <div className="text-xs">{planPartLabel(plan)}</div> : null}
                  </TableCell>
                  <TableCell>
                    {anyActive ? <Badge>Active</Badge> : <Badge variant="outline">Paused</Badge>}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" disabled={busy} aria-label="Actions">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {row.plans.map((item, index) => (
                          <div key={item.id}>
                            {grouped ? (
                              <>
                                {index > 0 ? <DropdownMenuSeparator /> : null}
                                <DropdownMenuLabel>{planPartLabel(item)}</DropdownMenuLabel>
                              </>
                            ) : null}
                            <DropdownMenuItem onClick={() => runMutation.mutate(item.id)}>
                              <Play className="mr-2 h-4 w-4" />
                              Generate next now
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => openEdit(item)}>
                              <Pencil className="mr-2 h-4 w-4" />
                              Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant="destructive"
                              onClick={() => deleteMutation.mutate(item.id)}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              Delete
                            </DropdownMenuItem>
                          </div>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      );
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <HorizontalScroll
          activeKey={planType}
          aria-label="Service plan types, scroll horizontally"
          className="sm:max-w-[calc(100%-12rem)]"
          data-testid="service-plan-tabs-scroll"
        >
          <div
            role="group"
            aria-label="Service plan type"
            className="inline-flex min-w-max items-center justify-center rounded-lg bg-muted p-[3px]"
          >
            {TABS.map((tab) => (
              <Button
                key={tab.value}
                type="button"
                size="sm"
                variant={planType === tab.value ? "secondary" : "ghost"}
                aria-pressed={planType === tab.value}
                className="h-8 shrink-0 px-2 py-1 shadow-none"
                onClick={() => setPlanType(tab.value)}
              >
                {tab.label}
              </Button>
            ))}
          </div>
        </HorizontalScroll>
        {newButton}
      </div>
      {body}
      <ServicePlanDialog open={dialogOpen} onOpenChange={setDialogOpen} plan={editing} />
    </div>
  );
}
