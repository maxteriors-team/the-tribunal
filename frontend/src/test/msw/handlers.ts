/**
 * MSW request handlers — default stubs for the most-used backend endpoints.
 *
 * These provide a "happy-path" baseline so a component test that doesn't care
 * about API details can render without exploding on an unhandled fetch.
 * Individual tests should override a specific endpoint with `server.use(...)`
 * rather than editing this file.
 *
 * URL conventions
 * ---------------
 * The axios client uses a relative baseURL in the browser (jsdom), so requests
 * resolve against `http://localhost:3000` and we match by absolute pattern
 * `http://localhost:3000/api/v1/...`. We also register the direct backend
 * origin (`http://localhost:8000`) so SSR/Node code paths that bypass the
 * Next.js proxy are covered.
 */
import { http, HttpResponse } from "msw";

import type { AgentsListResponse } from "@/lib/api/agents";
import type { ContactsListResponse } from "@/lib/api/contacts";
import type { DashboardResponse } from "@/lib/api/dashboard";
import type { WorkspaceWithMembership } from "@/lib/api/workspaces";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FIXED_NOW = "2026-01-01T00:00:00.000Z";

export const stubWorkspace: WorkspaceWithMembership = {
  workspace: {
    id: "ws_test_default",
    name: "Test Workspace",
    slug: "test-workspace",
    description: null,
    settings: {},
    is_active: true,
    created_at: FIXED_NOW,
    updated_at: FIXED_NOW,
  },
  role: "owner",
  is_default: true,
};

export const stubContactsList: ContactsListResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 50,
  pages: 0,
};

export const stubAgentsList: AgentsListResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 50,
  pages: 0,
};

export const stubDashboard: DashboardResponse = {
  stats: {
    total_contacts: 0,
    active_campaigns: 0,
    calls_today: 0,
    messages_sent: 0,
    contacts_change: "+0%",
    campaigns_change: "+0%",
    calls_change: "+0%",
    messages_change: "+0%",
  },
  recent_activity: [],
  campaign_stats: [],
  agent_stats: [],
  today_overview: { completed: 0, pending: 0, failed: 0 },
  appointment_stats: {
    appointments_today: 0,
    appointments_this_week: 0,
    show_up_rate_30d: null,
    no_shows_30d: 0,
    completed_30d: 0,
  },
  revenue_stats: {
    currency: "USD",
    won_value: 0,
    won_value_this_month: 0,
    won_count: 0,
    pipeline_value: 0,
    open_count: 0,
    lost_value: 0,
    lost_count: 0,
    appointments_booked_this_month: 0,
    estimated_ai_cost_this_month: 0,
    roi_multiple: null,
    by_agent: [],
    by_campaign: [],
    by_prompt_version: [],
  },
  speed_to_lead_stats: {
    window_days: 30,
    sla_seconds: 300,
    leads_measured: 0,
    within_sla: 0,
    pct_within_sla: null,
    avg_response_seconds: null,
    median_response_seconds: null,
    fastest_response_seconds: null,
  },
  reviews_stats: {
    average_rating: 0,
    total_reviews: 0,
    reputation_score: 0,
    new_count: 0,
    public_reviews: 0,
    private_feedback: 0,
    requests_sent: 0,
    requests_rated: 0,
    response_rate: 0,
  },
  deal_coach_stats: {
    open_deals: 0,
    at_risk_count: 0,
    critical_count: 0,
    watch_count: 0,
    next_best_action_count: 0,
    total_amount_at_risk: 0,
    currency: "USD",
    top_deals: [],
  },
  roleplay_stats: {
    total_runs: 0,
    runs_this_week: 0,
    completed_runs: 0,
    avg_overall_score: null,
    last_run_at: null,
  },
  knowledge_base_stats: {
    total_documents: 0,
    active_documents: 0,
    total_chunks: 0,
    total_tokens: 0,
    agents_with_knowledge: 0,
  },
  lead_source_roi_stats: {
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
  },
};

// ---------------------------------------------------------------------------
// Origin matrix — register the same path on both origins the app may hit.
// ---------------------------------------------------------------------------

const ORIGINS = ["http://localhost:3000", "http://localhost:8000"] as const;

function both<TPath extends string>(path: TPath): readonly [string, string] {
  return [`${ORIGINS[0]}${path}`, `${ORIGINS[1]}${path}`] as const;
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

export const handlers = [
  // Workspaces
  ...both("/api/v1/workspaces").map((url) =>
    http.get(url, () => HttpResponse.json([stubWorkspace])),
  ),

  // Contacts list
  ...both("/api/v1/workspaces/:workspaceId/contacts").map((url) =>
    http.get(url, () => HttpResponse.json(stubContactsList)),
  ),

  // Agents list
  ...both("/api/v1/workspaces/:workspaceId/agents").map((url) =>
    http.get(url, () => HttpResponse.json(stubAgentsList)),
  ),

  // Dashboard stats
  ...both("/api/v1/workspaces/:workspaceId/dashboard/stats").map((url) =>
    http.get(url, () => HttpResponse.json(stubDashboard)),
  ),
];
