import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReferralPartnerScoreboardRow } from "@/lib/api/referral-partners";

import { ReferralPartnerScoreboard } from "./referral-partner-scoreboard";

function row(
  overrides: Partial<ReferralPartnerScoreboardRow> = {},
): ReferralPartnerScoreboardRow {
  return {
    partner_id: "partner-1",
    name: "Dana Ruiz",
    company: "Keller Williams",
    partner_type: "realtor",
    is_active: true,
    referrals_sent: 4,
    jobs_closed: 2,
    close_rate: 0.5,
    total_revenue: 12000,
    average_job_value: 6000,
    last_referral_at: "2026-07-28T12:00:00Z",
    days_since_last_referral: 2,
    is_gone_quiet: false,
    ...overrides,
  };
}

function renderBoard(
  rows: ReferralPartnerScoreboardRow[],
  props: { callList?: boolean } = {},
) {
  return render(
    <ReferralPartnerScoreboard
      rows={rows}
      currency="USD"
      quietAfterDays={60}
      {...props}
    />,
  );
}

/** The row for a named partner, so assertions cannot leak across rows. */
function rowFor(name: string): HTMLElement {
  const cell = screen.getByRole("link", { name });
  const tableRow = cell.closest("tr");
  if (!tableRow) throw new Error(`No row rendered for ${name}`);
  return tableRow;
}

describe("ReferralPartnerScoreboard", () => {
  it("renders a semantic table with every production column", () => {
    renderBoard([row()]);

    expect(screen.getByRole("table")).toBeInTheDocument();
    for (const header of [
      "Partner",
      "Booked revenue",
      "Close rate",
      "Booked jobs",
      "Avg booked value",
      "Last referral",
    ]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
  });

  it("shows each rate beside the referral count it was computed from", () => {
    // A rate without its denominator is not a fact: "50%" on 4 referrals is
    // coachable, on 1 referral it is noise.
    renderBoard([row()]);

    const dana = rowFor("Dana Ruiz");
    expect(within(dana).getByText("50%")).toBeInTheDocument();
    expect(within(dana).getByText(/4 referrals/)).toBeInTheDocument();
    expect(within(dana).getByText("$12,000.00")).toBeInTheDocument();
    expect(within(dana).getByText("$6,000.00")).toBeInTheDocument();
  });

  it("flags a thin sample rather than presenting the rate as settled", () => {
    renderBoard([row({ referrals_sent: 1, jobs_closed: 1, close_rate: 1 })]);

    expect(screen.getByText(/1 referral · low sample/)).toBeInTheDocument();
  });

  it("renders an unknown rate as a dash, never as 0%", () => {
    renderBoard([
      row({
        name: "Zoe New",
        referrals_sent: 0,
        jobs_closed: 0,
        close_rate: null,
        total_revenue: 0,
        average_job_value: null,
        last_referral_at: null,
        days_since_last_referral: null,
      }),
    ]);

    const zoe = rowFor("Zoe New");
    expect(within(zoe).queryByText("0%")).not.toBeInTheDocument();
    expect(within(zoe).getByText("Never referred")).toBeInTheDocument();
  });

  it("links every partner to their detail view", () => {
    renderBoard([row()]);

    expect(screen.getByRole("link", { name: "Dana Ruiz" })).toHaveAttribute(
      "href",
      "/referral-partners/partner-1",
    );
  });

  it("marks a quiet partner on the full scoreboard", () => {
    renderBoard([row({ is_gone_quiet: true, days_since_last_referral: 91 })]);

    expect(screen.getByText("Quiet")).toBeInTheDocument();
    expect(screen.getByText("91 days ago")).toBeInTheDocument();
  });

  it("drops the redundant quiet badge in call-list mode", () => {
    // Every row in the call list is quiet, so the badge is pure noise there.
    renderBoard([row({ is_gone_quiet: true, days_since_last_referral: 91 })], {
      callList: true,
    });

    expect(screen.queryByText("Quiet")).not.toBeInTheDocument();
    expect(screen.getByText("91 days ago")).toBeInTheDocument();
  });

  it("marks a retired partner without hiding their history", () => {
    renderBoard([row({ is_active: false })]);

    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(screen.getByText("$12,000.00")).toBeInTheDocument();
  });

  it("states the applied quiet window so the reader is not guessing", () => {
    renderBoard([row()]);

    expect(screen.getByText(/quiet after 60 days/i)).toBeInTheDocument();
  });
});
