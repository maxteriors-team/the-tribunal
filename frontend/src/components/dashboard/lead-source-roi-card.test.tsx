import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LeadSourceRoiCard } from "@/components/dashboard/lead-source-roi-card";
import type {
  LeadSourceRoiStats,
  SourceRoiRow,
} from "@/lib/api/dashboard";

function row(overrides: Partial<SourceRoiRow> = {}): SourceRoiRow {
  return {
    rank: 1,
    source_type: "facebook_ads",
    source_name: "Facebook Ads",
    lead_source_id: "src-fb",
    spend: 5000,
    closed_won_jobs: 8,
    closed_won_revenue: 42000,
    cost_per_closed_won_job: 625,
    revenue_per_closed_won_job: 5250,
    roi_multiple: 8.4,
    net_revenue: 37000,
    currency: "USD",
    attribution_confidence: {
      average_score: 0.9,
      level: "high",
      attributed_closed_won_jobs: 8,
      total_closed_won_jobs: 10,
      notes: [],
    },
    is_winner: true,
    ...overrides,
  };
}

function stats(overrides: Partial<LeadSourceRoiStats> = {}): LeadSourceRoiStats {
  return {
    currency: "USD",
    rows: [
      row(),
      row({
        rank: 2,
        source_type: "google_ads",
        source_name: "Google Ads",
        lead_source_id: "src-g",
        spend: 3000,
        closed_won_jobs: 4,
        closed_won_revenue: 16000,
        cost_per_closed_won_job: 750,
        roi_multiple: 5.3,
        is_winner: false,
      }),
      row({
        rank: 3,
        source_type: "phone_radio",
        source_name: "Phone / Radio",
        lead_source_id: "src-p",
        spend: 0,
        closed_won_jobs: 2,
        closed_won_revenue: 6000,
        cost_per_closed_won_job: null,
        roi_multiple: null,
        is_winner: false,
      }),
    ],
    winner: {
      has_winner: true,
      source_type: "facebook_ads",
      source_name: "Facebook Ads",
      lead_source_id: "src-fb",
      rank_by: "roi",
      spend: 5000,
      closed_won_jobs: 8,
      closed_won_revenue: 42000,
      roi_multiple: 8.4,
      net_revenue: 37000,
      currency: "USD",
      reason: "",
      attribution_confidence: {
        average_score: 0.9,
        level: "high",
        attributed_closed_won_jobs: 8,
        total_closed_won_jobs: 10,
        notes: [],
      },
    },
    total_spend: 8000,
    total_closed_won_jobs: 14,
    total_closed_won_revenue: 64000,
    source_types_ranked: ["facebook_ads", "google_ads", "organic", "phone_radio"],
    ...overrides,
  };
}

function emptyStats(): LeadSourceRoiStats {
  return {
    currency: "USD",
    rows: [],
    winner: {
      has_winner: false,
      source_type: null,
      source_name: null,
      lead_source_id: null,
      rank_by: "none",
      spend: 0,
      closed_won_jobs: 0,
      closed_won_revenue: 0,
      roi_multiple: null,
      net_revenue: 0,
      currency: "USD",
      reason: "No closed-won jobs with attributed lead-source data yet.",
      attribution_confidence: {
        average_score: null,
        level: "unknown",
        attributed_closed_won_jobs: 0,
        total_closed_won_jobs: 0,
        notes: [],
      },
    },
    total_spend: 0,
    total_closed_won_jobs: 0,
    total_closed_won_revenue: 0,
    source_types_ranked: ["facebook_ads", "google_ads", "organic", "phone_radio"],
  };
}

describe("LeadSourceRoiCard", () => {
  it("highlights the winning source with its ROI and confidence", () => {
    render(<LeadSourceRoiCard stats={stats()} isPending={false} />);

    expect(screen.getByText("Winning Lead Source")).toBeInTheDocument();
    expect(screen.getByText("Winning lead source")).toBeInTheDocument();
    // ROI multiple shows in both the winner banner and the table row.
    expect(screen.getAllByText("8.4×").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText(/\(8\/10 jobs attributed\)/)).toBeInTheDocument();
    // The winning row is badged.
    expect(screen.getByText("Winner")).toBeInTheDocument();
  });

  it("renders each ranked source with spend, cost-per-job, and ROI", () => {
    render(<LeadSourceRoiCard stats={stats()} isPending={false} />);

    // Appears both as the row name and the channel sub-label.
    expect(screen.getAllByText("Google Ads").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("5.3×")).toBeInTheDocument();
    expect(screen.getByText("$750.00")).toBeInTheDocument();

    // Phone/Radio had no spend → cost-per-job and ROI are blanked.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });

  it("shows a no-winner explanation when nothing is attributed", () => {
    render(<LeadSourceRoiCard stats={emptyStats()} isPending={false} />);

    expect(screen.getByText("No winning source yet")).toBeInTheDocument();
    expect(
      screen.getByText("No closed-won jobs with attributed lead-source data yet."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No attributed closed-won jobs yet."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders a loading state without a table while pending", () => {
    render(<LeadSourceRoiCard stats={undefined} isPending />);

    expect(screen.getByText("Winning Lead Source")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("Winner")).not.toBeInTheDocument();
  });
});
