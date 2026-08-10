import { expect, test, type Page, type Request } from "@playwright/test";

const WORKSPACE_ID = "0ef615a3-4fa5-43e7-bb3b-2dbfa0788001";
const CURRENT_JOB_ID = "d0a60384-1859-4fb0-a1a4-e33119bd4001";
const FUTURE_JOB_ID = "d0a60384-1859-4fb0-a1a4-e33119bd4002";
const PAST_JOB_ID = "d0a60384-1859-4fb0-a1a4-e33119bd4003";
const FIXTURE_ID = "bc491f6a-2b68-4aa6-8337-c69ec31df001";
const BULB_ID = "bc491f6a-2b68-4aa6-8337-c69ec31df002";
const QUOTE_ID = "8033af21-3505-4476-8be4-ea6c481c1001";
const LINE_ID = "6c5e45fd-7984-4216-8ff4-988c03cc1001";
const BULB_LINE_ID = "6c5e45fd-7984-4216-8ff4-988c03cc1002";
const CUSTOM_LINE_ID = "6c5e45fd-7984-4216-8ff4-988c03cc1003";
const PUBLIC_TOKEN = "onsite-proposal-token";

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

function quoteResponse(status = "draft", publicToken: string | null = null) {
  return {
    id: QUOTE_ID,
    number: "Q-1048",
    status,
    public_token: publicToken,
    contact_id: 71,
    currency: "USD",
    subtotal: 385,
    discount_amount: 0,
    tax_amount: 0,
    total: 385,
    attach_count: 3,
    attach_value: 385,
    deposit_percentage: 100,
    deposit_amount: 385,
    deposit_required: true,
    created_at: "2026-08-10T15:30:00Z",
    updated_at: "2026-08-10T15:30:00Z",
    line_items: [
      {
        id: LINE_ID,
        quote_id: QUOTE_ID,
        name: "ZDC modern path light",
        description: "Add a fixture along the walkway.",
        quantity: 2,
        unit_price: 125,
        discount: 0,
        total: 250,
        service_category: "Lighting",
        created_at: "2026-08-10T15:30:00Z",
        updated_at: "2026-08-10T15:30:00Z",
      },
      {
        id: BULB_LINE_ID,
        quote_id: QUOTE_ID,
        name: "LED bulb replacement",
        description: "Replace a failed outdoor bulb.",
        quantity: 3,
        unit_price: 20,
        discount: 0,
        total: 60,
        service_category: "Lighting",
        created_at: "2026-08-10T15:30:00Z",
        updated_at: "2026-08-10T15:30:00Z",
      },
      {
        id: CUSTOM_LINE_ID,
        quote_id: QUOTE_ID,
        name: "Lift rental",
        description: null,
        quantity: 1,
        unit_price: 75,
        discount: 0,
        total: 75,
        service_category: null,
        created_at: "2026-08-10T15:30:00Z",
        updated_at: "2026-08-10T15:30:00Z",
      },
    ],
    proposal_document: null,
  };
}

async function installLeadTechApi(page: Page) {
  const quoteRequests: unknown[] = [];
  const presentRequests: string[] = [];
  const deliveryRequests: unknown[] = [];
  const paymentRequests: string[] = [];
  const unexpectedRequests: string[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;

    if (request.method() === "GET" && pathname === "/api/v1/auth/me") {
      await route.fulfill(
        json({
          id: 41,
          email: "lead.tech@example.com",
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
            role: "lead_technician",
            is_default: true,
          },
        ]),
      );
      return;
    }

    if (request.method() === "GET" && pathname.endsWith("/upsell/jobs")) {
      await route.fulfill(
        json({
          items: [
            {
              id: FUTURE_JOB_ID,
              contact_id: 72,
              title: "Roofline lighting install",
              status: "scheduled",
              scheduled_start: "2026-08-12T14:00:00Z",
            },
            {
              id: CURRENT_JOB_ID,
              contact_id: 71,
              title: "Front-yard lighting install",
              status: "in_progress",
              scheduled_start: "2026-08-10T14:00:00Z",
            },
            {
              id: PAST_JOB_ID,
              contact_id: 70,
              title: "Patio lighting service",
              status: "completed",
              scheduled_start: "2026-08-03T14:00:00Z",
            },
          ],
          total: 3,
        }),
      );
      return;
    }

    if (request.method() === "GET" && pathname.endsWith("/upsell/my-stats")) {
      await route.fulfill(
        json({
          period_start: "2026-08-01",
          period_end: "2026-08-31",
          proposals_sent: 4,
          proposals_approved: 2,
          revenue_approved: 875,
          close_rate: 0.5,
          care_plans_sold: 1,
          rank: null,
        }),
      );
      return;
    }

    if (
      request.method() === "GET" &&
      pathname === `/api/v1/workspaces/${WORKSPACE_ID}/upsell/jobs/${CURRENT_JOB_ID}/customer`
    ) {
      await route.fulfill(
        json({
          contact_id: 71,
          full_name: "Avery Martinez",
          phone_number: "+15125550171",
          email: "avery@example.com",
          address_line1: "1842 Garden Path",
          address_city: "Austin",
          address_state: "TX",
          address_zip: "78704",
        }),
      );
      return;
    }

    if (request.method() === "GET" && pathname.endsWith("/upsell/catalog")) {
      await route.fulfill(
        json({
          items: [
            {
              id: FIXTURE_ID,
              name: "ZDC modern path light",
              description: "Add a fixture along the walkway.",
              unit_price: 125,
              price_unit: "each",
              service_category: "Lighting",
              taxable: true,
              attach_targets: [],
            },
            {
              id: BULB_ID,
              name: "LED bulb replacement",
              description: "Replace a failed outdoor bulb.",
              unit_price: 20,
              price_unit: "each",
              service_category: "Lighting",
              taxable: true,
              attach_targets: [],
            },
          ],
          proposal_limit: 500,
          total: 2,
        }),
      );
      return;
    }

    if (request.method() === "GET" && pathname.endsWith("/upsell/care-plans")) {
      await route.fulfill(
        json({
          configured: true,
          fixture_count: Number(url.searchParams.get("fixture_count") ?? 0),
          free_fixtures: 10,
          options: [
            {
              key: "essential",
              name: "Essential",
              price: 199,
              base_price: 199,
              per_fixture_price: 0,
              description: "Annual system check and priority scheduling.",
              features: ["Annual system check", "Priority scheduling"],
            },
          ],
        }),
      );
      return;
    }

    if (
      request.method() === "POST" &&
      pathname === `/api/v1/workspaces/${WORKSPACE_ID}/upsell/jobs/${CURRENT_JOB_ID}/quote`
    ) {
      quoteRequests.push(parseRequestBody(request));
      await route.fulfill(json(quoteResponse()));
      return;
    }

    if (
      request.method() === "POST" &&
      pathname ===
        `/api/v1/workspaces/${WORKSPACE_ID}/upsell/jobs/${CURRENT_JOB_ID}/quote/${QUOTE_ID}/present`
    ) {
      presentRequests.push(pathname);
      await route.fulfill(json(quoteResponse("sent", PUBLIC_TOKEN)));
      return;
    }

    if (request.method() === "GET" && pathname === `/api/v1/p/quotes/${PUBLIC_TOKEN}`) {
      await route.fulfill(
        json({
          token: PUBLIC_TOKEN,
          number: "Q-1048",
          title: "On-site lighting additions",
          status: "sent",
          currency: "USD",
          subtotal: 385,
          tax_amount: 0,
          discount_amount: 0,
          total: 385,
          issue_date: "2026-08-10",
          expiry_date: "2026-09-09",
          is_expired: false,
          is_decided: false,
          client_name: "Avery Martinez",
          deposit_percentage: 100,
          deposit_amount: 385,
          deposit_paid: false,
          deposit_required: true,
          packages: [],
          line_items: [
            {
              name: "ZDC modern path light",
              description: "Add a fixture along the walkway.",
              quantity: 2,
              unit_price: 125,
              discount: 0,
              total: 250,
            },
            {
              name: "LED bulb replacement",
              description: "Replace a failed outdoor bulb.",
              quantity: 3,
              unit_price: 20,
              discount: 0,
              total: 60,
            },
            {
              name: "Lift rental",
              description: null,
              quantity: 1,
              unit_price: 75,
              discount: 0,
              total: 75,
            },
          ],
          branding: {
            business_name: "Maxteriors",
            logo_url: null,
            brand_color: "#d3a900",
            accent_color: "#f5c842",
            business_address: null,
            business_phone: "+15125550100",
            business_email: "hello@example.com",
            footer: null,
          },
          proposal_document: null,
        }),
      );
      return;
    }

    if (
      request.method() === "POST" &&
      pathname === `/api/v1/p/quotes/${PUBLIC_TOKEN}/approve`
    ) {
      paymentRequests.push(pathname);
      await route.fulfill(
        json({
          status: "approved",
          deposit_required: true,
          deposit_amount: 385,
          deposit_paid: false,
        }),
      );
      return;
    }

    if (
      request.method() === "POST" &&
      pathname === `/api/v1/p/quotes/${PUBLIC_TOKEN}/deposit-checkout`
    ) {
      paymentRequests.push(pathname);
      await route.fulfill(
        json({ url: `${new URL(page.url()).origin}/mock-stripe-checkout` }),
      );
      return;
    }

    if (request.method() === "POST" && pathname === `/api/v1/p/quotes/${PUBLIC_TOKEN}/view`) {
      await route.fulfill(json({}));
      return;
    }

    if (
      request.method() === "POST" &&
      pathname ===
        `/api/v1/workspaces/${WORKSPACE_ID}/upsell/jobs/${CURRENT_JOB_ID}/quote/${QUOTE_ID}/deliver`
    ) {
      deliveryRequests.push(parseRequestBody(request));
      await route.fulfill(json({ channel: "sms", ok: true, to: "+15125550171" }));
      return;
    }

    if (
      request.method() === "GET" &&
      (pathname.endsWith("/nudges/stats") || pathname.endsWith("/pending-actions/stats"))
    ) {
      await route.fulfill(json({}));
      return;
    }

    unexpectedRequests.push(`${request.method()} ${pathname}`);
    await route.fulfill(json({ detail: "Unexpected test request" }));
  });

  return {
    quoteRequests,
    presentRequests,
    deliveryRequests,
    paymentRequests,
    unexpectedRequests,
  };
}

function parseRequestBody(request: Request): unknown {
  const raw = request.postData();
  return raw ? JSON.parse(raw) : null;
}

async function addCustomLine(page: Page) {
  const customSection = page.getByRole("region", { name: "Custom line items" });
  await customSection.getByRole("button", { name: "Add custom" }).click();
  await customSection.getByLabel("Description").fill("Lift rental");
  await customSection.getByLabel("Quantity").fill("1");
  await customSection.getByLabel("Price each").fill("75");
}

async function assertNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
}

test.describe("lead technician on-site upsell", () => {
  test("builds and texts an add-on proposal from the assigned job", async ({ page }, testInfo) => {
    const api = await installLeadTechApi(page);
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.goto("/upsell");

    await expect(page.getByRole("heading", { name: "Sell an add-on" })).toBeVisible();
    await expect(page.getByText("Pick the job you are on.")).toBeVisible();
    const jobButtons = page.getByRole("button").filter({
      hasText: /lighting install|lighting service/,
    });
    await expect(jobButtons.first()).toContainText("Front-yard lighting install");
    await expect(jobButtons.first()).toContainText("In progress now");
    await assertNoHorizontalOverflow(page);
    await testInfo.attach("job-picker", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });

    await page.getByRole("button", { name: /Front-yard lighting install/ }).click();

    await expect(page.getByRole("heading", { name: "Avery Martinez" })).toBeVisible();
    await expect(page.getByText("1842 Garden Path, Austin")).toBeVisible();
    await expect(page.getByText("ZDC modern path light")).toBeVisible();

    const fixtureRow = page.getByRole("listitem").filter({ hasText: "ZDC modern path light" });
    await fixtureRow.getByRole("button", { name: /^ZDC modern path light/ }).click();
    await fixtureRow.getByRole("button", { name: /^Add one ZDC modern path light$/ }).click();

    const bulbRow = page.getByRole("listitem").filter({ hasText: "LED bulb replacement" });
    await bulbRow.getByRole("button", { name: /^LED bulb replacement/ }).click();
    await bulbRow.getByRole("button", { name: /^Add one LED bulb replacement$/ }).click();
    await bulbRow.getByRole("button", { name: /^Add one LED bulb replacement$/ }).click();

    await addCustomLine(page);

    await expect(page.getByText("3 add-ons")).toBeVisible();
    await expect(page.getByText("$385.00", { exact: true })).toBeVisible();
    await assertNoHorizontalOverflow(page);
    await testInfo.attach("proposal-builder", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });

    await page.getByRole("button", { name: "Build proposal" }).click();

    await expect(page.getByRole("heading", { name: "Proposal Q-1048 is ready" })).toBeVisible();
    expect(api.quoteRequests).toEqual([
      {
        line_items: [
          { catalog_item_id: FIXTURE_ID, quantity: 2 },
          { catalog_item_id: BULB_ID, quantity: 3 },
        ],
        custom_line_items: [{ name: "Lift rental", quantity: 1, unit_price: 75 }],
        care_plan: null,
      },
    ]);

    await page.getByRole("button", { name: "Share proposal" }).click();
    const dialog = page.getByRole("dialog", { name: "Share this proposal" });
    await expect(dialog).toContainText("Avery Martinez");
    await expect(dialog).toContainText("$385.00 of work");
    await expect(dialog.getByRole("button", { name: "Present in person" })).toBeVisible();
    await dialog.getByRole("button", { name: "Send text" }).click();

    await expect(page.getByRole("heading", { name: "Proposal sent" })).toBeVisible();
    expect(api.deliveryRequests).toEqual([{ channel: "sms" }]);
    expect(api.unexpectedRequests).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });

  test("opens the proposal and takes an in-person approval to payment", async ({ page }) => {
    const api = await installLeadTechApi(page);
    await page.goto("/upsell");
    await page.getByRole("button", { name: /Front-yard lighting install/ }).click();

    await page
      .getByRole("listitem")
      .filter({ hasText: "ZDC modern path light" })
      .getByRole("button", { name: /^ZDC modern path light/ })
      .click();
    await page
      .getByRole("listitem")
      .filter({ hasText: "LED bulb replacement" })
      .getByRole("button", { name: /^LED bulb replacement/ })
      .click();
    await addCustomLine(page);

    await page.getByRole("button", { name: "Build proposal" }).click();
    await page.getByRole("button", { name: "Share proposal" }).click();
    await page
      .getByRole("dialog", { name: "Share this proposal" })
      .getByRole("button", { name: "Present in person" })
      .click();

    await expect(page).toHaveURL(`/p/quotes/${PUBLIC_TOKEN}`);
    await expect(page.getByText("Investment Summary")).toBeVisible();
    await expect(page.getByText("ZDC modern path light")).toBeVisible();
    await expect(page.getByText("LED bulb replacement")).toBeVisible();
    await expect(page.getByText("Lift rental")).toBeVisible();
    await expect(page.getByText("Payment Due Today")).toBeVisible();
    await page.waitForTimeout(250);
    await page.getByRole("button", { name: /Approve & Pay Now/ }).click();

    await expect(page).toHaveURL(/\/mock-stripe-checkout$/);
    expect(api.presentRequests).toHaveLength(1);
    expect(api.deliveryRequests).toEqual([]);
    expect(api.paymentRequests).toEqual([
      `/api/v1/p/quotes/${PUBLIC_TOKEN}/approve`,
      `/api/v1/p/quotes/${PUBLIC_TOKEN}/deposit-checkout`,
    ]);
    expect(api.unexpectedRequests).toEqual([]);
  });

  test("keeps every primary touch target at least 44px on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await installLeadTechApi(page);
    await page.goto("/upsell");
    await page.getByRole("button", { name: /Front-yard lighting install/ }).click();
    await expect(page.getByText("ZDC modern path light")).toBeVisible();

    const targets = [
      page.getByRole("button", { name: "All jobs" }),
      page.getByRole("button", { name: /^ZDC modern path light/ }),
      page.getByRole("button", { name: "Build proposal" }),
    ];

    for (const target of targets) {
      const box = await target.boundingBox();
      expect(box, "touch target should be rendered").not.toBeNull();
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
    await assertNoHorizontalOverflow(page);

    await targets[1].click();
    await addCustomLine(page);
    await targets[2].click();
    await page.getByRole("button", { name: "Share proposal" }).click();
    const dialog = page.getByRole("dialog", { name: "Share this proposal" });
    await page.waitForTimeout(250);
    const dialogTargets = [
      dialog.getByRole("button", { name: "Not yet" }),
      dialog.getByRole("button", { name: "Present in person" }),
      dialog.getByRole("button", { name: "Send text" }),
    ];
    for (const target of dialogTargets) {
      const box = await target.boundingBox();
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
    await assertNoHorizontalOverflow(page);

    await dialogTargets[1].click();
    await expect(page).toHaveURL(`/p/quotes/${PUBLIC_TOKEN}`);
    await expect(page.getByText("Investment Summary")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Qty" })).toBeHidden();
    await expect(page.getByText("2 × $125.00")).toBeVisible();
    await expect(page.getByText("Lift rental")).toBeVisible();
    await page.waitForTimeout(250);
    const approveButton = page.getByRole("button", { name: /Approve & Pay Now/i });
    const approveBox = await approveButton.boundingBox();
    expect(approveBox?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(approveBox?.height ?? 0).toBeGreaterThanOrEqual(44);
    await assertNoHorizontalOverflow(page);
  });
});
