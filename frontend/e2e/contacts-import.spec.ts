import { test, expect, type Page } from "@playwright/test";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const STAMP = "2026-09-10T12:00:00Z";

// Exercise the real app router and dialog without credentials or customer data.
async function mockImportApi(page: Page) {
  const workspace = {
    id: WORKSPACE_ID,
    name: "Synthetic import workspace",
    slug: "import-e2e",
    settings: { timezone: "America/New_York" },
    onboarding_completed_at: STAMP,
    is_active: true,
    created_at: STAMP,
    updated_at: STAMP,
  };
  const prefix = `/api/v1/workspaces/${WORKSPACE_ID}`;
  const responses: Record<string, unknown> = {
    "/api/v1/auth/me": {
      id: 999999,
      email: "import@example.invalid",
      full_name: "Synthetic operator",
      is_active: true,
      default_workspace_id: WORKSPACE_ID,
      created_at: STAMP,
    },
    "/api/v1/workspaces": [{ workspace, role: "owner", is_default: true }],
    [prefix]: workspace,
    [`${prefix}/contacts`]: {
      items: [], total: 0, page: 1, page_size: 25, pages: 0,
      status_counts: { all: 0, new: 0, contacted: 0, qualified: 0, converted: 0, lost: 0 },
    },
    [`${prefix}/contacts/stats`]: {
      new_leads_30d: 0, new_leads_change: "+0%", new_clients_30d: 0,
      new_clients_change: "+0%", total_new_clients_ytd: 0,
    },
    [`${prefix}/contacts/import/preview`]: {
      headers: ["phone_number", "first_name"],
      sample_rows: [{ phone_number: "+15555550100", first_name: "Synthetic" }],
      total_rows: 1,
      suggested_mapping: { phone_number: "phone_number", first_name: "first_name" },
      contact_fields: [
        { name: "phone_number", label: "Phone Number", required: true },
        { name: "first_name", label: "First Name", required: false },
      ],
    },
    [`${prefix}/contacts/import`]: {
      total_rows: 1, successful: 1, failed: 0, skipped_duplicates: 0, errors: [],
    },
    [`${prefix}/dashboard/today-queue`]: { items: [], generated_at: STAMP },
    [`${prefix}/dashboard/stats`]: {
      stats: {
        leads_last_24_hours: 0, total_contacts: 0, active_campaigns: 0,
        calls_today: 0, messages_sent: 0, contacts_change: "+0%",
        campaigns_change: "+0%", calls_change: "+0%", messages_change: "+0%",
      },
      recent_activity: [], campaign_stats: [], agent_stats: [],
      today_overview: { completed: 0, pending: 0, failed: 0 },
      appointment_stats: {
        appointments_today: 0, appointments_this_week: 0,
        show_up_rate_30d: null, no_shows_30d: 0, completed_30d: 0,
      },
      revenue_stats: null, lead_source_roi_stats: null,
      speed_to_lead_stats: {
        window_days: 30, sla_seconds: 300, leads_measured: 0, within_sla: 0,
        pct_within_sla: null, avg_response_seconds: null,
        median_response_seconds: null, fastest_response_seconds: null,
      },
      reviews_stats: {
        average_rating: 0, total_reviews: 0, reputation_score: 0, new_count: 0,
        public_reviews: 0, private_feedback: 0, requests_sent: 0,
        requests_rated: 0, response_rate: 0,
      },
      deal_coach_stats: {
        open_deals: 0, at_risk_count: 0, critical_count: 0, watch_count: 0,
        next_best_action_count: 0, total_amount_at_risk: 0, currency: "USD", top_deals: [],
      },
      roleplay_stats: {
        total_runs: 0, runs_this_week: 0, completed_runs: 0,
        avg_overall_score: null, last_run_at: null,
      },
      knowledge_base_stats: {
        total_documents: 0, active_documents: 0, total_chunks: 0,
        total_tokens: 0, agents_with_knowledge: 0,
      },
    },
    [`${prefix}/lead-sources`]: [],
    [`${prefix}/lead-source-capture`]: { require_lead_source_on_manual_create: false },
    [`${prefix}/tags`]: [],
    [`${prefix}/custom-fields`]: [],
    [`${prefix}/custom-fields/definitions`]: [],
    [`${prefix}/conversations/unread-summary`]: { unread_conversations: 0, unread_messages: 0 },
    [`${prefix}/nudges/stats`]: { pending: 0, snoozed: 0, completed: 0, dismissed: 0 },
    [`${prefix}/pending-actions/stats`]: {
      pending: 0, approved: 0, rejected: 0, expired: 0, total: 0,
    },
    [`${prefix}/notifications/unread-count`]: { count: 0 },
  };

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith("/api/")) {
      return ["localhost", "127.0.0.1"].includes(url.hostname)
        ? route.continue()
        : route.abort("blockedbyclient");
    }
    const body = responses[url.pathname.replace(/\/$/, "")];
    return route.fulfill({
      status: body === undefined ? 404 : 200,
      json: body ?? { detail: "No synthetic fixture for this endpoint" },
    });
  });
}

async function expectContactsUrl(page: Page, suffix = "") {
  await expect(page).toHaveURL((url) =>
    url.pathname === "/contacts" && `${url.search}${url.hash}` === suffix,
  );
}

test.beforeEach(async ({ page }) => {
  await mockImportApi(page);
});

for (const suffix of ["", "?source=segment&tag=Fall+Cleanup&tag=VIP#contacts"]) {
  test(`direct import URL retains contacts${suffix ? ", other parameters and hash" : ""}`, async ({ page }) => {
    await page.goto("/today");
    await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
    const previousHistoryLength = await page.evaluate(() => history.length);

    const importUrl = suffix
      ? `/contacts${suffix.replace("?", "?import=true&")}`
      : "/contacts?import=true";
    await page.goto(importUrl);
    await expectContactsUrl(page, suffix);
    const dialog = page.getByRole("dialog", { name: "Import Contacts", exact: true });
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("heading", { name: "Contacts", exact: true, includeHidden: true })).toBeAttached();
    expect(await page.evaluate(() => history.length)).toBe(previousHistoryLength + 1);

    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expectContactsUrl(page, suffix);
    await page.goBack();
    await expect(page).toHaveURL(/\/today$/);
    await page.goForward();
    await expectContactsUrl(page, suffix);
    await expect(page.getByRole("heading", { name: "Contacts", exact: true })).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
}

test("dashboard import stays open through completion and preserves back/forward", async ({ page }) => {
  await page.goto("/dashboard");
  const entry = page.getByRole("link", { name: "Import Contacts", exact: true });
  await expect(entry).toBeVisible();
  const previousHistoryLength = await page.evaluate(() => history.length);
  await entry.click();

  await expectContactsUrl(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Import Contacts", exact: true })).toBeVisible();
  expect(await page.evaluate(() => history.length)).toBe(previousHistoryLength + 1);

  await dialog.locator('input[type="file"]').setInputFiles({
    name: "synthetic.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("phone_number,first_name\n+15555550100,Synthetic\n"),
  });
  await expect(dialog.getByRole("heading", { name: "Map Fields", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "Import Options", exact: true })).toBeVisible();
  await expectContactsUrl(page);
  await dialog.getByRole("button", { name: "Import Contacts", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "Import Complete", exact: true })).toBeVisible();
  await expect(dialog.getByText("Imported", { exact: true })).toBeVisible();
  await expectContactsUrl(page);
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expectContactsUrl(page);

  await page.goBack();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(entry).toBeVisible();
  await page.goForward();
  await expectContactsUrl(page);
  await expect(page.getByRole("heading", { name: "Contacts", exact: true })).toBeVisible();
  await expect(dialog).toHaveCount(0);

  // A fresh request must still open a previously visited, now-closed dialog.
  await page.goBack();
  await expect(entry).toBeVisible();
  await entry.click();
  await expectContactsUrl(page);
  await expect(dialog.getByRole("heading", { name: "Import Contacts", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expectContactsUrl(page);
});
