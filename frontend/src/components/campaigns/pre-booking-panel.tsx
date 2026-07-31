"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { preBookingApi } from "@/lib/api/pre-booking-campaigns";
import { formatAmountTerm } from "@/lib/pre-booking";
import { queryKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils/date";
import { formatCurrency } from "@/lib/utils/number";
import type { PreBookingLeadTimeStatus, PreBookingReservationStatus } from "@/types";

const LEAD_TIME_STYLES: Record<
  PreBookingLeadTimeStatus,
  { className: string; label: string }
> = {
  ample: {
    className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
    label: "Good runway",
  },
  tight: {
    className: "border-amber-500/40 bg-amber-500/10 text-amber-700",
    label: "Tight runway",
  },
  late: {
    className: "border-destructive/40 bg-destructive/10 text-destructive",
    label: "Late",
  },
};

const RESERVATION_STYLES: Record<PreBookingReservationStatus, string> = {
  held: "bg-amber-500/10 text-amber-700 border-amber-500/30",
  confirmed: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30",
  released: "bg-muted text-muted-foreground",
  cancelled: "bg-muted text-muted-foreground",
};

/**
 * The pre-booking side of a campaign: what season it sells, on what terms, and
 * how much of the crew's calendar it has already spent.
 *
 * Slots are the number worth staring at. Sends and reply rates say how the
 * campaign is performing; slots say what the business has actually committed to
 * delivering in a month that has not happened yet.
 */
export function PreBookingPanel({ campaignId }: { campaignId: string }) {
  const workspaceId = useWorkspaceId() ?? "";

  const { data: offer, isPending } = useQuery({
    queryKey: queryKeys.preBooking.offer(workspaceId, campaignId),
    queryFn: () => preBookingApi.getOffer(workspaceId, campaignId),
    enabled: !!workspaceId,
  });

  const { data: reservations } = useQuery({
    queryKey: queryKeys.preBooking.reservations(workspaceId, campaignId),
    queryFn: () => preBookingApi.listReservations(workspaceId, campaignId),
    enabled: !!workspaceId,
  });

  if (isPending) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Pre-Booking</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!offer) return null;

  const sold = offer.slots_held + offer.slots_confirmed;
  const fillPercent = offer.slot_cap > 0 ? Math.min(100, (sold / offer.slot_cap) * 100) : 0;
  const leadTime = LEAD_TIME_STYLES[offer.lead_time_status];
  const LeadIcon = offer.lead_time_status === "ample" ? CheckCircle2 : TriangleAlert;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <CalendarClock className="size-5 text-muted-foreground" />
          Pre-Booking · {offer.season_label}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className={`flex items-start gap-3 rounded-lg border p-4 ${leadTime.className}`}>
          <LeadIcon className="mt-0.5 size-5 shrink-0" />
          <div className="space-y-1">
            <p className="text-sm font-medium">{leadTime.label}</p>
            <p className="text-sm">{offer.lead_time_message}</p>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-muted-foreground">Season slots</span>
            <span className="text-sm font-medium">
              {sold} of {offer.slot_cap} sold
            </span>
          </div>
          <Progress value={fillPercent} className="h-2" />
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span>{offer.slots_confirmed} confirmed (deposit paid)</span>
            <span>{offer.slots_held} held</span>
            <span>{offer.slots_remaining} left</span>
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-4 text-sm">
          <Fact label="Selling" value={offer.service_description} />
          <Fact
            label="Work window"
            value={`${formatDate(offer.season_start_date)} – ${formatDate(offer.season_end_date)}`}
          />
          <Fact
            label="Booking discount"
            value={`${formatAmountTerm(offer.incentive_type, offer.incentive_value)} off`}
          />
          <Fact
            label="Deposit to hold"
            value={formatAmountTerm(offer.deposit_type, offer.deposit_value)}
          />
          <Fact label="Unpaid holds expire after" value={`${offer.hold_hours}h`} />
          <Fact
            label="Launches"
            value={offer.scheduled_start ? formatDate(offer.scheduled_start) : "Immediately"}
          />
        </dl>

        <div className="space-y-2">
          <h4 className="text-sm font-medium">Reservations</h4>
          {reservations && reservations.length > 0 ? (
            <ul className="divide-y rounded-lg border">
              {reservations.map((reservation) => (
                <li
                  key={reservation.id}
                  className="flex items-center justify-between gap-4 p-3 text-sm"
                >
                  <div>
                    <div className="font-medium">Contact #{reservation.contact_id}</div>
                    <div className="text-xs text-muted-foreground">
                      {reservation.status === "held"
                        ? `Hold expires ${formatDate(reservation.hold_expires_at)}`
                        : `Booked for ${formatDate(reservation.target_start_date)}`}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {reservation.deposit_amount != null && (
                      <span className="text-muted-foreground">
                        {formatCurrency(reservation.deposit_amount)} deposit
                      </span>
                    )}
                    <Badge variant="outline" className={RESERVATION_STYLES[reservation.status]}>
                      {reservation.status}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              No slots claimed yet. Replies that accept the offer land here.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
