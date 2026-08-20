"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Handshake, MoreHorizontal, Pencil, PhoneOutgoing, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { referralPartnersApi, type ReferralPartner } from "@/lib/api/referral-partners";
import { queryKeys } from "@/lib/query-keys";
import { REALTIME } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";

import { formatMoney, partnerTypeLabel } from "./partner-metrics";
import { ReferralPartnerDialog } from "./referral-partner-dialog";
import { ReferralPartnerScoreboard } from "./referral-partner-scoreboard";

/** The three jobs this page serves, in the order an owner works through them. */
type PartnerView = "scoreboard" | "quiet" | "roster";

const TABS: { value: PartnerView; label: string }[] = [
  { value: "scoreboard", label: "Scoreboard" },
  { value: "quiet", label: "Went quiet" },
  { value: "roster", label: "Roster" },
];

/**
 * Silence windows an owner would actually pick. 30 days suits a partner who
 * refers monthly; 90 forgives seasonal trades who were never going to send work
 * in February.
 */
const QUIET_WINDOWS = [30, 60, 90, 180] as const;

const DEFAULT_QUIET_AFTER_DAYS = 60;

export function ReferralPartnersPage() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  // Reads are open to any workspace member; the write routes require
  // manager-and-up, which `crm:write` mirrors exactly. Hiding the affordances is
  // UX only — the API still enforces the gate.
  const { can } = useCapabilities();
  const canManage = can("crm:write");
  const [view, setView] = useState<PartnerView>("scoreboard");
  const [quietAfterDays, setQuietAfterDays] = useState<number>(DEFAULT_QUIET_AFTER_DAYS);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ReferralPartner | null>(null);

  const isCallList = view === "quiet";
  const scoreboardParams = {
    quiet_after_days: quietAfterDays,
    gone_quiet_only: isCallList,
  };

  const scoreboardQuery = useQuery({
    queryKey: queryKeys.referralPartners.scoreboard(workspaceId ?? "", scoreboardParams),
    queryFn: () => referralPartnersApi.scoreboard(workspaceId ?? "", scoreboardParams),
    enabled: Boolean(workspaceId) && view !== "roster",
    ...REALTIME,
  });

  const rosterQuery = useQuery({
    queryKey: queryKeys.referralPartners.list(workspaceId ?? ""),
    queryFn: () => referralPartnersApi.list(workspaceId ?? ""),
    enabled: Boolean(workspaceId) && view === "roster",
  });

  const invalidate = () => {
    if (!workspaceId) return;
    void queryClient.invalidateQueries({
      queryKey: queryKeys.referralPartners.all(workspaceId),
    });
  };

  const deleteMutation = useMutation({
    mutationFn: (id: string) => referralPartnersApi.delete(workspaceId ?? "", id),
    onSuccess: () => {
      toast.success("Referral partner deleted");
      invalidate();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to delete partner")),
  });

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const openEdit = (partner: ReferralPartner) => {
    setEditing(partner);
    setDialogOpen(true);
  };

  const newButton = canManage ? (
    <Button onClick={openCreate} size="sm">
      <Plus className="mr-1.5 size-4" aria-hidden />
      New partner
    </Button>
  ) : null;

  const activeQuery = view === "roster" ? rosterQuery : scoreboardQuery;

  let body: React.ReactNode;
  if (!workspaceId || activeQuery.isLoading) {
    body = <PageLoadingState message="Loading referral partners..." />;
  } else if (activeQuery.isError) {
    body = (
      <PageErrorState
        message={getApiErrorMessage(activeQuery.error, "Failed to load referral partners")}
        onRetry={() => void activeQuery.refetch()}
      />
    );
  } else if (view === "roster") {
    const partners = rosterQuery.data?.items ?? [];
    body =
      partners.length === 0 ? (
        <PageEmptyState
          icon={<Handshake className="size-8" />}
          title="No referral partners yet"
          description="Add the realtors, insurance agents, trades, and networking contacts who send you work. Referrals then get credited by name instead of piling into one anonymous bucket."
          action={newButton ?? undefined}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Partner</TableHead>
              <TableHead>Relationship</TableHead>
              <TableHead>Contact</TableHead>
              <TableHead>Status</TableHead>
              {canManage ? (
                <TableHead className="w-10">
                  <span className="sr-only">Actions</span>
                </TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {partners.map((partner) => (
              <TableRow key={partner.id} className={partner.is_active ? undefined : "opacity-60"}>
                <TableCell className="max-w-[16rem]">
                  <Link
                    href={`/referral-partners/${partner.id}`}
                    className="truncate font-medium underline-offset-4 hover:underline"
                  >
                    {partner.name}
                  </Link>
                  {partner.company ? (
                    <div className="truncate text-xs text-muted-foreground">{partner.company}</div>
                  ) : null}
                </TableCell>
                <TableCell>
                  <Badge variant="outline">{partnerTypeLabel(partner.partner_type)}</Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {partner.phone || partner.email || "Not recorded"}
                </TableCell>
                <TableCell>
                  {partner.is_active ? (
                    <Badge>Active</Badge>
                  ) : (
                    <Badge variant="outline">Inactive</Badge>
                  )}
                </TableCell>
                {canManage ? (
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={deleteMutation.isPending}
                          aria-label={`Actions for ${partner.name}`}
                        >
                          <MoreHorizontal className="size-4" aria-hidden />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => openEdit(partner)}>
                          <Pencil className="mr-2 size-4" aria-hidden />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant="destructive"
                          onClick={() => deleteMutation.mutate(partner.id)}
                        >
                          <Trash2 className="mr-2 size-4" aria-hidden />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                ) : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      );
  } else {
    const board = scoreboardQuery.data;
    const rows = board?.items ?? [];
    if (rows.length === 0) {
      body = isCallList ? (
        <PageEmptyState
          icon={<PhoneOutgoing className="size-8" />}
          title="Nobody has gone quiet"
          description={`Every partner who has ever referred has sent work in the last ${quietAfterDays} days. Widen the window to look further back.`}
        />
      ) : (
        <PageEmptyState
          icon={<Handshake className="size-8" />}
          title="No referral partners yet"
          description="Add the realtors, insurance agents, trades, and networking contacts who send you work, then pick them on new leads. Their referrals, close rate, and revenue show up here."
          action={newButton ?? undefined}
        />
      );
    } else {
      body = (
        <div className="space-y-3">
          {board ? (
            <p className="text-sm text-muted-foreground">
              {isCallList ? (
                <>
                  <span className="font-medium text-foreground">{formatNumber(board.total)}</span>{" "}
                  {board.total === 1 ? "partner has" : "partners have"} gone quiet, worth{" "}
                  <span className="font-medium text-foreground">
                    {formatMoney(board.total_revenue, board.currency)}
                  </span>{" "}
                  of past work.
                </>
              ) : (
                <>
                  <span className="font-medium text-foreground">{formatNumber(board.total)}</span>{" "}
                  {board.total === 1 ? "partner" : "partners"} sent{" "}
                  <span className="font-medium text-foreground">
                    {formatNumber(board.total_referrals_sent)}
                  </span>{" "}
                  {board.total_referrals_sent === 1 ? "referral" : "referrals"}, closing{" "}
                  <span className="font-medium text-foreground">
                    {formatNumber(board.total_jobs_closed)}
                  </span>{" "}
                  {board.total_jobs_closed === 1 ? "job" : "jobs"} worth{" "}
                  <span className="font-medium text-foreground">
                    {formatMoney(board.total_revenue, board.currency)}
                  </span>
                  .
                </>
              )}
            </p>
          ) : null}
          <ReferralPartnerScoreboard
            rows={rows}
            currency={board?.currency ?? "USD"}
            quietAfterDays={board?.quiet_after_days ?? quietAfterDays}
            callList={isCallList}
          />
        </div>
      );
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div
          role="group"
          aria-label="Referral partner view"
          className="inline-flex h-9 items-center justify-center rounded-lg bg-muted p-[3px]"
        >
          {TABS.map((tab) => (
            <Button
              key={tab.value}
              type="button"
              size="sm"
              variant={view === tab.value ? "secondary" : "ghost"}
              aria-pressed={view === tab.value}
              className="h-[calc(100%-1px)] px-2 py-1 shadow-none"
              onClick={() => setView(tab.value)}
            >
              {tab.label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {view === "roster" ? null : (
            <div className="space-y-1">
              <Label htmlFor="quiet-window" className="text-xs text-muted-foreground">
                Quiet after
              </Label>
              <Select
                value={String(quietAfterDays)}
                onValueChange={(value) => setQuietAfterDays(Number(value))}
              >
                <SelectTrigger id="quiet-window" className="w-[9.5rem]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {QUIET_WINDOWS.map((days) => (
                    <SelectItem key={days} value={String(days)}>
                      {days} days
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {newButton}
        </div>
      </div>
      {body}
      <ReferralPartnerDialog open={dialogOpen} onOpenChange={setDialogOpen} partner={editing} />
    </div>
  );
}
