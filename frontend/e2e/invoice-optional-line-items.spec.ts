import { expect, test, type Page, type Request } from "@playwright/test";

const WORKSPACE_ID = "0ef615a3-4fa5-43e7-bb3b-2dbfa0788001";
const INVOICE_ID = "6c5e45fd-7984-4216-8ff4-988c03cc2001";
const REQUIRED_ITEM_ID = "6c5e45fd-7984-4216-8ff4-988c03cc2002";
const OPTIONAL_ITEM_ID = "6c5e45fd-7984-4216-8ff4-988c03cc2003";
const PUBLIC_INVOICE_TOKEN = "optional-invoice-token";

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const contact = {
  id: 71,
  user_id: 41,
  workspace_id: WORKSPACE_ID,
  first_name: "Avery",
  last_name: "Martinez",
  email: "avery@example.com",
  phone_number: "+15125550171",
  status: "lead",
  created_at: "2026-08-10T15:30:00Z",
  updated_at: "2026-08-10T15:30:00Z",
};

function publicInvoice() {
  return {
    token: PUBLIC_INVOICE_TOKEN,
    number: "INV-001048",
    status: "sent",
    currency: "USD",
    line_items: [
      {
        id: REQUIRED_ITEM_ID,
        name: "House wash",
        description: null,
        quantity: 1,
        unit_price: 200,
        discount: 0,
        total: 200,
        is_optional: false,
        is_selected: true,
      },
      {
        id: OPTIONAL_ITEM_ID,
        name: "Gutter brightening",
        description: "Restore the visible gutter faces.",
        quantity: 1,
        unit_price: 75,
        discount: 0,
        total: 75,
        is_optional: true,
        is_selected: true,
      },
    ],
    subtotal: 275,
    tax_amount: 0,
    discount_amount: 0,
    total: 275,
    amount_paid: 0,
    balance_due: 275,
    issue_date: "2026-08-10",
    due_date: "2026-08-24",
    is_paid: false,
    is_void: false,
    is_overdue: false,
    is_payable: true,
    client_name: "Avery Martinez",
    notes: "Thank you for choosing Maxteriors.",
    terms: null,
    branding: {
      business_name: "Maxteriors Exterior Care",
      logo_url: null,
      brand_color: "#171717",
      accent_color: "#c9a84c",
      business_address: "1842 Garden Path, Austin, TX",
      business_phone: "512-555-0171",
      business_email: "hello@maxteriors.example",
      footer: null,
    },
  };
}

async function installInvoiceApi(page: Page) {
  const createRequests: unknown[] = [];
  const paymentRequests: unknown[] = [];

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

    if (request.method() === "GET" && pathname === `/api/v1/workspaces/${WORKSPACE_ID}/invoices`) {
      await route.fulfill(json({ items: [], total: 0, page: 1, page_size: 100, pages: 0 }));
      return;
    }

    if (request.method() === "GET" && pathname === `/api/v1/workspaces/${WORKSPACE_ID}/contacts`) {
      await route.fulfill(json({ items: [contact], total: 1, page: 1, page_size: 100 }));
      return;
    }

    if (request.method() === "POST" && pathname === `/api/v1/workspaces/${WORKSPACE_ID}/invoices`) {
      createRequests.push(parseRequestBody(request));
      await route.fulfill(json({ id: INVOICE_ID, number: "INV-001048", status: "draft" }));
      return;
    }

    if (request.method() === "GET" && pathname === `/api/v1/p/invoices/${PUBLIC_INVOICE_TOKEN}`) {
      await route.fulfill(json(publicInvoice()));
      return;
    }

    if (
      request.method() === "POST" &&
      pathname === `/api/v1/p/invoices/${PUBLIC_INVOICE_TOKEN}/pay`
    ) {
      paymentRequests.push(parseRequestBody(request));
      await route.fulfill(
        json({
          url: `${new URL(request.url()).origin}/p/invoices/${PUBLIC_INVOICE_TOKEN}?checkout=mock`,
          amount: 275,
          currency: "USD",
        }),
      );
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

  return { createRequests, paymentRequests };
}

function parseRequestBody(request: Request): unknown {
  const raw = request.postData();
  return raw ? JSON.parse(raw) : null;
}

async function assertNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
}

for (const viewport of [
  { name: "desktop", width: 1280, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const) {
  test(`${viewport.name}: sender marks an item optional and recipient chooses it`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const api = await installInvoiceApi(page);

    await page.goto("/invoices");
    await page.getByRole("button", { name: "New invoice" }).first().click();
    await page.getByRole("combobox").click();
    await page.getByRole("option", { name: /Avery Martinez/ }).click();
    await page.getByLabel("Line item 1 description").fill("House wash");
    await page.getByLabel("Line item 1 price").fill("200");
    await page.getByRole("button", { name: /add line/i }).click();
    await page.getByLabel("Line item 2 description").fill("Gutter brightening");
    await page.getByLabel("Line item 2 price").fill("75");
    await page.getByLabel("Optional item").nth(1).click();
    await expect(page.getByLabel("Optional item").nth(1)).toBeChecked();
    await assertNoHorizontalOverflow(page);
    await page.getByRole("button", { name: "Save draft" }).click();

    await expect.poll(() => api.createRequests.length).toBe(1);
    expect(api.createRequests[0]).toMatchObject({
      contact_id: 71,
      line_items: [
        { name: "House wash", unit_price: 200, is_optional: false },
        { name: "Gutter brightening", unit_price: 75, is_optional: true },
      ],
    });

    await page.goto(`/p/invoices/${PUBLIC_INVOICE_TOKEN}`);
    const option = page.getByRole("checkbox", { name: "Include Gutter brightening" });
    await expect(option).toBeChecked();
    await expect(page.getByText("$275.00").first()).toBeVisible();
    await assertNoHorizontalOverflow(page);
    // Capture the resting state after the shared invoice entrance animation.
    await page.waitForTimeout(900);
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-selected.png`),
      fullPage: true,
    });

    await option.click();
    await expect(option).not.toBeChecked();
    await expect(page.getByRole("status")).toContainText("Current total: $200.00");
    await expect(page.getByText("$200.00").first()).toBeVisible();
    await assertNoHorizontalOverflow(page);
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-excluded.png`),
      fullPage: true,
    });

    await option.click();
    await expect(option).toBeChecked();
    await page.getByRole("button", { name: /pay now/i }).click();
    await expect.poll(() => api.paymentRequests.length).toBe(1);
    expect(api.paymentRequests[0]).toEqual({
      selected_optional_line_item_ids: [OPTIONAL_ITEM_ID],
    });
  });
}
