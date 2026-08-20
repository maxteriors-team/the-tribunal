import { expect, test, type Page, type Request } from "@playwright/test";

const WORKSPACE_ID = "0ef615a3-4fa5-43e7-bb3b-2dbfa0788001";
const CAMPAIGN_ID = "6c5e45fd-7984-4216-8ff4-988c03cc2010";

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

function parseRequestBody(request: Request): Record<string, unknown> {
  const raw = request.postData();
  return raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
}

function campaignResponse(payload: Record<string, unknown>) {
  const timestamp = "2026-08-19T12:00:00Z";

  return {
    id: CAMPAIGN_ID,
    workspace_id: WORKSPACE_ID,
    campaign_type: "email",
    name: payload.name,
    description: payload.description ?? null,
    email_subject: payload.email_subject,
    status: "draft",
    from_phone_number: "",
    initial_message: payload.initial_message,
    timezone: "America/New_York",
    messages_per_minute: 30,
    follow_up_enabled: false,
    follow_up_delay_hours: 24,
    max_follow_ups: 0,
    ai_enabled: false,
    total_contacts: 0,
    messages_sent: 0,
    messages_delivered: 0,
    messages_failed: 0,
    replies_received: 0,
    contacts_qualified: 0,
    contacts_opted_out: 0,
    appointments_booked: 0,
    appointments_completed: 0,
    links_clicked: 0,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

async function installCampaignApi(page: Page) {
  const createRequests: Record<string, unknown>[] = [];
  let savedCampaign: ReturnType<typeof campaignResponse> | null = null;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (request.method() === "GET" && pathname === "/api/v1/auth/me") {
      await route.fulfill(
        json({
          id: 41,
          email: "owner@example.com",
          full_name: "Jordan Lee",
          is_active: true,
          created_at: "2026-01-01T00:00:00Z",
          default_workspace_id: WORKSPACE_ID,
        }),
      );
      return;
    }

    if (request.method() === "GET" && pathname === "/api/v1/workspaces") {
      await route.fulfill(
        json([
          {
            workspace: {
              id: WORKSPACE_ID,
              name: "Maxteriors",
              slug: "maxteriors",
              description: null,
              settings: {},
              is_active: true,
              onboarding_completed_at: "2026-01-01T00:00:00Z",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
            role: "owner",
            is_default: true,
          },
        ]),
      );
      return;
    }

    const campaignsPath = `/api/v1/workspaces/${WORKSPACE_ID}/campaigns`;

    if (request.method() === "POST" && pathname === campaignsPath) {
      const payload = parseRequestBody(request);
      createRequests.push(payload);
      savedCampaign = campaignResponse(payload);
      await route.fulfill(json(savedCampaign, 201));
      return;
    }

    if (request.method() === "GET" && pathname === `${campaignsPath}/${CAMPAIGN_ID}`) {
      await route.fulfill(
        savedCampaign
          ? json(savedCampaign)
          : json({ detail: "Campaign has not been created" }, 404),
      );
      return;
    }

    if (request.method() === "GET" && pathname === `${campaignsPath}/${CAMPAIGN_ID}/analytics`) {
      await route.fulfill(
        json({
          delivery_rate: 0,
          reply_rate: 0,
          qualification_rate: 0,
        }),
      );
      return;
    }

    if (request.method() === "GET" && pathname === `/api/v1/workspaces/${WORKSPACE_ID}/contacts`) {
      await route.fulfill(json({ items: [], total: 0, page: 1, page_size: 100, pages: 0 }));
      return;
    }

    if (
      request.method() === "GET" &&
      (pathname.includes("/agents") ||
        pathname.includes("/phone-numbers") ||
        pathname.includes("/offers") ||
        pathname.includes("/segments"))
    ) {
      await route.fulfill(json({ items: [], total: 0 }));
      return;
    }

    if (
      request.method() === "GET" &&
      (pathname.endsWith("/nudges/stats") || pathname.endsWith("/pending-actions/stats"))
    ) {
      await route.fulfill(json({}));
      return;
    }

    await route.fulfill({
      ...json({ detail: `Unexpected ${request.method()} ${pathname}` }),
      status: 404,
    });
  });

  return { createRequests };
}

test("campaign launcher opens real builders and clearly disables multi-channel", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await installCampaignApi(page);

  const choices = [
    { name: "SMS Campaign", path: "/campaigns/sms/new" },
    { name: "Email Campaign", path: "/campaigns/email/new" },
    { name: "Voice Campaign", path: "/campaigns/voice/new" },
    { name: "Pre-Booking Campaign", path: "/campaigns/pre-booking/new" },
  ] as const;

  for (const choice of choices) {
    await page.goto("/campaigns/new");
    const builderLink = page.getByRole("link", { name: new RegExp(choice.name) });
    await expect(builderLink).toHaveAttribute("href", choice.path);
    await builderLink.click();
    await expect(page).toHaveURL(new RegExp(`${choice.path}$`), { timeout: 30_000 });
  }

  await page.goto("/campaigns/new");
  await expect(page.getByLabel("Campaign Name")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save as Draft" })).toHaveCount(0);

  const multiChannel = page
    .locator('[aria-disabled="true"]')
    .filter({ hasText: "Multi-Channel Campaign" });
  await expect(multiChannel).toContainText("Coming soon");
  await expect(multiChannel).toContainText("Unavailable");
  await multiChannel.click();
  await expect(page).toHaveURL(/\/campaigns\/new$/);
});

test("email wizard preserves entered data and saves drafts to their detail page", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const api = await installCampaignApi(page);
  const campaignName = "Fall gutter follow-up";
  const subject = "Your fall gutter service is ready";
  const body = "Hi {{first_name}}, reply to reserve your fall gutter cleaning.";

  await page.goto("/campaigns/new");
  await page.getByRole("link", { name: /Email Campaign/ }).click();

  await page.getByLabel("Campaign Name").fill(campaignName);
  await page.getByLabel("Subject Line").fill(subject);
  await page.getByLabel("Email Body").fill(body);

  // A rerender from recipient filtering must not reset the composed message.
  await page.getByLabel("Campaign Name").press("Tab");
  await expect(page.getByLabel("Campaign Name")).toHaveValue(campaignName);
  await expect(page.getByLabel("Subject Line")).toHaveValue(subject);
  await expect(page.getByLabel("Email Body")).toHaveValue(body);

  await page.getByRole("button", { name: "Save as Draft" }).click();

  await expect.poll(() => api.createRequests.length).toBe(1);
  expect(api.createRequests[0]).toMatchObject({
    name: campaignName,
    campaign_type: "email",
    email_subject: subject,
    initial_message: body,
  });

  await expect(page).toHaveURL(new RegExp(`/campaigns/${CAMPAIGN_ID}$`), {
    timeout: 30_000,
  });
  await expect(page.getByRole("heading", { name: campaignName })).toBeVisible();
  await expect(page.getByText(body)).toBeVisible();
});
