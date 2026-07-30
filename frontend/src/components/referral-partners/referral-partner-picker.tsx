"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { referralPartnersApi } from "@/lib/api/referral-partners";
import { queryKeys } from "@/lib/query-keys";

import { partnerTypeLabel } from "./partner-metrics";

const NONE_VALUE = "__none__";

/**
 * Pick which named partner sent this lead.
 *
 * Only active partners are listed: crediting a retired partner would corrupt the
 * scoreboard, and the API rejects it anyway. When the roster is empty the control
 * says so and links to where partners are added, rather than presenting an empty
 * dropdown the operator cannot resolve.
 */
export function ReferralPartnerPicker({
  workspaceId,
  value,
  onChange,
  onClear,
  id,
  "aria-label": ariaLabel = "Referral partner",
}: {
  workspaceId: string;
  value: string | undefined;
  onChange: (partnerId: string) => void;
  onClear?: () => void;
  id?: string;
  "aria-label"?: string;
}) {
  const params = { is_active: true };
  const { data, isPending } = useQuery({
    queryKey: queryKeys.referralPartners.list(workspaceId, params),
    queryFn: () => referralPartnersApi.list(workspaceId, params),
    enabled: Boolean(workspaceId),
  });

  const options = data?.items ?? [];

  if (!isPending && options.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No referral partners yet.{" "}
        <Link
          href="/referral-partners"
          className="font-medium underline underline-offset-4"
        >
          Add the people who send you work
        </Link>{" "}
        to credit them by name.
      </p>
    );
  }

  return (
    <Select
      value={value ?? NONE_VALUE}
      onValueChange={(next) => {
        if (next === NONE_VALUE) {
          onClear?.();
          return;
        }
        onChange(next);
      }}
      disabled={isPending}
    >
      <SelectTrigger id={id} aria-label={ariaLabel} className="w-full">
        <SelectValue
          placeholder={isPending ? "Loading partners…" : "Who referred them?"}
        />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE_VALUE}>Not sure / no partner</SelectItem>
        {options.map((partner) => (
          <SelectItem key={partner.id} value={partner.id}>
            {partner.name}
            {partner.company ? ` · ${partner.company}` : ""} (
            {partnerTypeLabel(partner.partner_type)})
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
