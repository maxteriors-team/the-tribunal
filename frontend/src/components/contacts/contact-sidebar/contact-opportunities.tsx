"use client";

import { useQuery } from "@tanstack/react-query";
import { KanbanSquare, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { OpportunityCreateSheet } from "@/components/opportunities/opportunity-create-sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { STATIC } from "@/lib/query-options";
import { formatCurrency } from "@/lib/utils/number";
import { useWorkspace } from "@/providers/workspace-provider";
import type { Contact, Opportunity, OpportunityStatus, Pipeline } from "@/types";

/** Deals shown inline before the section defers to the board. */
const VISIBLE_DEALS = 3;

/** Enough to know whether this lead is already on the board, not a deal log. */
const DEALS_PAGE_SIZE = 20;

const STATUS_VARIANT: Record<
  OpportunityStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  open: "secondary",
  won: "default",
  lost: "destructive",
  abandoned: "outline",
};

interface ContactOpportunitiesProps {
  workspaceId: string | null | undefined;
  contact: Contact;
}

/**
 * Deal name pre-filled when adding from a contact.
 *
 * Mirrors the backend's auto-pipeline naming (``opportunity_name``) so a card
 * added by hand here reads the same as one automation opened, and the board
 * does not end up with two naming conventions.
 */
function defaultDealName(contact: Contact): string {
  const fullName = [contact.first_name, contact.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
  const company = (contact.company_name ?? "").trim();
  if (fullName && company) return `${fullName} — ${company}`;
  return fullName || company || "New deal";
}

/**
 * This contact's pipeline cards, with a way to add one.
 *
 * Operators work a lead from the conversation, so the decision "this is a real
 * deal" happens here — not on the board. Existing cards are listed first on
 * purpose: without them the button invites a duplicate card for a lead that is
 * already in the pipeline.
 */
export function ContactOpportunities({
  workspaceId,
  contact,
}: ContactOpportunitiesProps) {
  const { currentWorkspace } = useWorkspace();
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isPending } = useQuery({
    queryKey: queryKeys.opportunities.list(workspaceId ?? "", {
      contact_id: contact.id,
    }),
    queryFn: () =>
      opportunitiesApi.list(workspaceId!, {
        contact_id: contact.id,
        page_size: DEALS_PAGE_SIZE,
      }),
    enabled: !!workspaceId,
  });

  const { data: pipelines } = useQuery({
    queryKey: queryKeys.opportunities.pipelines(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.listPipelines(workspaceId!),
    enabled: !!workspaceId,
    ...STATIC,
  });

  // The promotion flow and the board both use the earliest active pipeline;
  // mirror that so a card added here lands on the board the operator sees.
  const defaultPipeline = useMemo<Pipeline | undefined>(() => {
    if (!pipelines || pipelines.length === 0) return undefined;
    return [...pipelines].sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    )[0];
  }, [pipelines]);

  const stageNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const pipeline of pipelines ?? []) {
      for (const stage of pipeline.stages ?? []) {
        names.set(stage.id, stage.name);
      }
    }
    return names;
  }, [pipelines]);

  // Trust, then verify: an API that ignores `contact_id` (an older deploy, or a
  // regression in the filter) answers with the whole workspace board, and every
  // contact would appear to own deals that are not theirs. Filtering here makes
  // the panel wrong-empty instead of wrong-full.
  const opportunities: Opportunity[] = (data?.items ?? []).filter(
    (deal) => deal.primary_contact_id === contact.id,
  );
  const canAssignOwners = currentWorkspace?.role !== "sales_rep";
  // One add control per state: the header "+" once cards exist, the empty-state
  // button before that. Two buttons for the same action reads like two actions.
  const showHeaderAdd = !!defaultPipeline && opportunities.length > 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2">
        <h3 className="text-sm font-medium text-muted-foreground">Pipeline</h3>
        {showHeaderAdd ? (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            title="Add another deal"
            aria-label="Add another deal"
            data-testid="contact-add-opportunity"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="h-4 w-4" />
          </Button>
        ) : null}
      </div>

      {isPending ? (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="space-y-2 px-2">
          {opportunities.slice(0, VISIBLE_DEALS).map((deal) => (
            <Link
              key={deal.id}
              href="/opportunities"
              className="flex items-center gap-2 p-2 rounded-lg bg-muted/30 text-xs transition-colors hover:bg-muted/60"
            >
              <KanbanSquare className="h-3 w-3 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{deal.name}</p>
                <p className="text-muted-foreground text-xs truncate">
                  {(deal.stage_id ? stageNames.get(deal.stage_id) : null) ??
                    "No stage"}
                  {deal.amount != null
                    ? ` · ${formatCurrency(deal.amount, deal.currency)}`
                    : ""}
                </p>
              </div>
              <Badge
                variant={STATUS_VARIANT[deal.status]}
                className="text-xs py-0 capitalize"
              >
                {deal.status}
              </Badge>
            </Link>
          ))}

          {opportunities.length > VISIBLE_DEALS ? (
            <Button variant="outline" size="sm" className="w-full text-xs" asChild>
              <Link href="/opportunities">
                View all ({opportunities.length})
              </Link>
            </Button>
          ) : null}

          {opportunities.length === 0 ? (
            defaultPipeline ? (
              <>
                <p className="text-xs text-muted-foreground">
                  Not in the pipeline yet
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full text-xs"
                  data-testid="contact-add-opportunity"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus className="h-3 w-3" />
                  Add to pipeline
                </Button>
              </>
            ) : (
              <p className="text-xs text-muted-foreground py-2">
                No pipeline yet — create one on the Opportunities board first.
              </p>
            )
          ) : null}
        </div>
      )}

      {defaultPipeline && workspaceId ? (
        <OpportunityCreateSheet
          workspaceId={workspaceId}
          pipelineId={defaultPipeline.id}
          stages={[...(defaultPipeline.stages ?? [])].sort(
            (a, b) => a.order - b.order,
          )}
          contactId={contact.id}
          defaultName={defaultDealName(contact)}
          canAssignOwners={canAssignOwners}
          open={createOpen}
          onOpenChange={setCreateOpen}
        />
      ) : null}
    </div>
  );
}
