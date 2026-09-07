import { readFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Request } from "@playwright/test";

const PUBLIC_TOKEN = "permanent-client-quote-token";
const LOGO_URL = `data:image/png;base64,${readFileSync(
  "../backend/static/brand/maxteriors-logo.png",
).toString("base64")}`;
const MOCKUP_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAIAAABqhmJGAAAE8ElEQVR42u3bSXLTQBSAYa8hDEkgkAlnMmRgwYIVB2DFWTkH5+Ai4JSJUdkd27Hbkl73V/WvlAUgvU/qLtKDZ7sfJAVt4BZIAEsCWBLAEsCSAJYEsCSAJYAl9QbwUFLQAJZCA94bSgoawBLAkjoB/HxvKCloAEsASwJYEsBSRYDPJAUNYAlgSd0A3j+TFDSAJYAlASwJYAlgSQBL2iLgnf1zSUEDWAJYEsDK3p9f36e5GyUCfnOugmsCvjfsnpQVwAALYPUGavPiyXC0GDDSAKuP39gx3UkzPx1fWcpeAKszwFO68zV/aoENsIIBTpIGODrgC0XpgVniYibAbnKwAI5Ed4ZZE+GT3D5meJX3hQDW+no3sbqUcWOHnPhzPQiA1VPAFtgAKxtXgLUq4BdvL9SHmlSmF2cgtUY3CTj5F/bgug3g3umdqHjs/2/bb+b1sfiNI4AB7pLriiVfOgK4Fq7RAS9dYAvgkr+0zYszGELoXWWH7HG3A/hSLTQ37vcXe7LLzbVDTv57PfqtBnA3gINyXeWYxERy8oUlgAEOusA2AwCHsroAcPF6AQa4wF1uJXSThu2QAbZIDsy4uT22QwYYYAtsTQAfXOqp/Ru71EWA1wFsqNYN4HXozoxdt0cOygNMNcBb1zuZMBQz7pAXvyWVBvzy4EorZpHcyffZ4C0I4EVcAQYY4MBf2uZFu9yeAEYa4FUXyRO3BRw5iH5MYlzyGZlYgC2SIx2TSL5kARbAdsgAF7TLpdcOGeAYu9zmRhfdiMcklr6aiwb87qqqLJJL3SEnn2/x8wwwBkUvsCsAPCq1h0eYuAhwNYBHZTcomO7MI7TLrdDwKu90gPurl1XHJB52yInZABhgWWADvBlXgFUv4FfvRkGbPobpFQfr9STA8xMVTsEgNN3pY3DkQGsfk0jOFcDtATaR2rzkhwFggFXIAruvgN+Petv/W9m46MiBWgI8N409NDIG/LGHzd3K+4uOHKjlYxLJmeyVlBiADZY6PCax4KMCMMAKusAGGGABXBhgu1yFMAxwwq0U7phE7YANhEr4PZA6AXvwYhhgCeCYffn6Tdq8oPM/eH34KXQmT1kKOv8ASwADLIABBlgAAywBDLAABhhgAQwwwAIY4Mf7/fNHy5U0/QXcPYABBhjgDgBfh84IApwJcMj5Bxhgdy804KPr0BlBgPMAjjn/AAPs7gEMMMAAdwJ49+g6dBWO4OHJ2barEHDQ+QcYYIABBhhggAEGGGCAAQYY4IoA34QOYIAzAQ45/wADDDDAAAMMcDeAj29CBzDAeQDHnH+AAQYYYIABBhhggAEGGGCAAQYYYIABBhhggAHeIuC949vQAQxwloLOP8AAAwwwwAADDDDAAAP8RMAnt6EDGOA8gGPOP8AAAwwwwAADDDDAAAMMMMAAAwwwwABHAHwXOoABzgQ45PwDDDDAAAMMMMAAdwg4UD0EXEAAAwwwwK0D3j+9Cx3AAGcp6PwDDDDAAAMMMMAAAwwwwAADDHBFgD+HDmCAMwEOOf8AAwwwwAADDDDAAAMMMMAAA1wN4J3Tg9ABDHCWgs4/wAADDDDAAAMMMMAAA1wXYKnmAJYAlgSwJIAlgCUBLAlgSQBLAEsCWBLAEsCSAJYEsCSAJYAlASwJYEkASwBLAlgSwBLAkgCWBLAkgCWAJQEsCWBJAEvR+wvSOuFuvcT1KgAAAABJRU5ErkJggg==";

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const proposal = () => ({
  token: PUBLIC_TOKEN,
  number: "Q-2048",
  title: "Permanent lighting for your home",
  status: "sent",
  proposal_version: 7,
  currency: "USD",
  subtotal: 8475,
  tax_amount: 0,
  discount_amount: 0,
  total: 8475,
  payment_options: {
    fifty_percent_down_amount: 4237.5,
    completion_balance: 4237.5,
    pay_in_full_amount: 8475,
  },
  proposal_payment_choice: null,
  proposal_payment_amount: null,
  proposal_payment_paid: false,
  proposal_payment_required: false,
  financing: {
    provider: "GreenSky",
    plan_number: "6124",
    terms: [24],
    default_term: 24,
    apr: 0,
    monthly_payment: 417,
    monthly_by_term: { "24": 417 },
    disclaimer: "Estimated payment only. Subject to credit approval.",
  },
  issue_date: "2026-09-04",
  expiry_date: "2026-10-04",
  is_expired: false,
  is_decided: false,
  intro: "A permanent roofline lighting system designed for this home.",
  notes: "Final placement will be confirmed before installation.",
  terms: "Your selected payment schedule governs this proposal.",
  client_name: "Pat Lee",
  deposit_percentage: 50,
  deposit_amount: 4237.5,
  deposit_paid: false,
  deposit_required: true,
  price_range: null,
  packages: [],
  line_items: [
    {
      name: "Permanent roofline lighting",
      description: "Track, controller, installation, and commissioning.",
      quantity: 1,
      unit_price: 8475,
      discount: 0,
      total: 8475,
    },
  ],
  branding: {
    business_name: "Maxteriors",
    logo_url: LOGO_URL,
    brand_color: "#304854",
    accent_color: "#fcb400",
    business_address: "123 Service Lane, Austin, TX",
    business_phone: "+15125550100",
    business_email: "hello@example.com",
    footer: "Thank you for considering Maxteriors.",
  },
  proposal_document: {
    service: "permanent",
    mockups: [
      {
        image: MOCKUP_URL,
        caption: "Pat Lee home with proposed permanent roofline lighting",
      },
    ],
  },
});

interface Calls {
  approvals: unknown[];
  declines: unknown[];
  checkouts: { choice: string; amount: number }[];
  unexpected: string[];
}

function requestBody(request: Request): unknown {
  return request.postData() ? request.postDataJSON() : null;
}

async function installPublicQuoteApi(page: Page): Promise<Calls> {
  const calls: Calls = { approvals: [], declines: [], checkouts: [], unexpected: [] };

  await page.route("**/mock-stripe-checkout*", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "Checkout" }),
  );
  await page.route("**/api/v1/p/quotes/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const root = `/api/v1/p/quotes/${PUBLIC_TOKEN}`;

    if (request.method() === "GET" && pathname === root) {
      await route.fulfill(json(proposal()));
      return;
    }
    if (request.method() === "POST" && pathname === `${root}/view`) {
      await route.fulfill(json({}));
      return;
    }
    if (request.method() === "POST" && pathname === `${root}/approve`) {
      const body = requestBody(request) as { payment_option?: string };
      calls.approvals.push(body);
      const choice = body.payment_option;
      const amount = choice === "fifty_percent_down" ? 4237.5 : 8475;
      await route.fulfill(
        json({
          token: PUBLIC_TOKEN,
          status: "approved",
          message: "Proposal approved.",
          proposal_payment_choice: choice,
          proposal_payment_required: true,
          proposal_payment_amount: amount,
          deposit_required: false,
        }),
      );
      return;
    }
    if (request.method() === "POST" && pathname === `${root}/decline`) {
      calls.declines.push(requestBody(request));
      await route.fulfill(
        json({ token: PUBLIC_TOKEN, status: "declined", message: "Proposal declined." }),
      );
      return;
    }
    if (request.method() === "POST" && pathname === `${root}/payment-checkout`) {
      const approval = calls.approvals.at(-1) as { payment_option?: string } | undefined;
      const choice = approval?.payment_option ?? "";
      const amount = choice === "fifty_percent_down" ? 4237.5 : 8475;
      calls.checkouts.push({ choice, amount });
      await route.fulfill(
        json({
          url: `${new URL(page.url()).origin}/mock-stripe-checkout?choice=${choice}`,
          amount,
          currency: "USD",
          payment_choice: choice,
        }),
      );
      return;
    }

    calls.unexpected.push(`${request.method()} ${pathname}`);
    await route.fulfill(json({ detail: "Unexpected test request" }));
  });

  return calls;
}

async function assertNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
}

async function assertNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(
    results.violations.map(({ id, nodes }) => ({
      id,
      targets: nodes.flatMap((node) => node.target),
    })),
  ).toEqual([]);
}

test.describe("permanent lighting client proposal", () => {
  test("approves 50% down and redirects with the exact Stripe amount", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const calls = await installPublicQuoteApi(page);
    await page.goto(`/p/quotes/${PUBLIC_TOKEN}`);

    await expect(page.getByRole("img", { name: "Maxteriors" })).toBeVisible();
    await expect(
      page.getByRole("img", { name: "Pat Lee home with proposed permanent roofline lighting" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Project scope" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Estimated project range" })).toHaveCount(0);
    await expect(page.locator(".pq-range, .pq-amount, .pq-totals")).toHaveCount(0);
    await expect(page.locator(".pq-table")).not.toContainText("$");
    await expect(page.locator(".payment-option__price")).toHaveText([
      "$417/mo",
      "$4,237.50",
      "$8,475",
    ]);
    await expect(page.getByText("for 24 months")).toBeVisible();
    await expect(page.getByRole("radio", { name: /financing/i })).toHaveCount(0);
    await expect(page.getByText(/GreenSky|0% APR|plan 6124/i)).toHaveCount(0);
    await expect(page.locator(".payment-options__disclosure")).toHaveText(
      "Estimated payment only. Subject to credit approval.",
    );
    const down = page.getByRole("radio", { name: /50% down, \$4,237.50/i });
    const full = page.getByRole("radio", { name: /pay in full, \$8,475/i });
    await expect(down).not.toBeChecked();
    await expect(full).not.toBeChecked();
    await expect(page.getByText("Balance due at completion")).toBeVisible();
    await expect(page.getByText("$4,237.50 at completion")).toHaveCount(0);
    await assertNoHorizontalOverflow(page);
    await assertNoAxeViolations(page);
    await page.screenshot({
      path: "../.ezcoder/screenshots/permanent-client-quote-desktop.png",
      fullPage: true,
      animations: "disabled",
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await assertNoHorizontalOverflow(page);
    await assertNoAxeViolations(page);
    await expect(page.getByRole("heading", { name: "Project scope" })).toBeVisible();
    await page.screenshot({
      path: "../.ezcoder/screenshots/permanent-client-quote-mobile.png",
      fullPage: true,
      animations: "disabled",
    });

    await down.focus();
    await page.keyboard.press("Space");
    await expect(down).toBeChecked();
    const approve = page.getByRole("button", { name: /approve and pay \$4,237.50/i });
    await expect(approve).toBeEnabled();
    await approve.click();

    await expect(page).toHaveURL(/\/mock-stripe-checkout\?choice=fifty_percent_down$/);
    await expect
      .poll(() => calls.approvals)
      .toEqual([
        { proposal_version: 7, selected_tier: null, payment_option: "fifty_percent_down" },
      ]);
    expect(calls.checkouts).toEqual([{ choice: "fifty_percent_down", amount: 4237.5 }]);
    expect(calls.unexpected).toEqual([]);
  });

  test("approves pay in full and redirects with the full Stripe amount", async ({ page }) => {
    const calls = await installPublicQuoteApi(page);
    await page.goto(`/p/quotes/${PUBLIC_TOKEN}`);

    await page.getByRole("radio", { name: /pay in full, \$8,475/i }).check();
    await page.getByRole("button", { name: /approve and pay \$8,475/i }).click();

    await expect(page).toHaveURL(/\/mock-stripe-checkout\?choice=pay_in_full$/);
    await expect
      .poll(() => calls.approvals)
      .toEqual([{ proposal_version: 7, selected_tier: null, payment_option: "pay_in_full" }]);
    expect(calls.checkouts).toEqual([{ choice: "pay_in_full", amount: 8475 }]);
    expect(calls.unexpected).toEqual([]);
  });

  test("makes declining explicit and sends the entered reason", async ({ page }) => {
    const calls = await installPublicQuoteApi(page);
    await page.goto(`/p/quotes/${PUBLIC_TOKEN}`);

    await page.getByRole("button", { name: "No, decline" }).click();
    await page.getByRole("textbox", { name: "Optional reason" }).fill("Project timing changed");
    await page.getByRole("button", { name: "Confirm decline" }).click();

    await expect(
      page.getByText("You declined this proposal. Thanks for letting us know."),
    ).toBeVisible();
    await expect.poll(() => calls.declines).toEqual([{ reason: "Project timing changed" }]);
    expect(calls.approvals).toEqual([]);
    expect(calls.checkouts).toEqual([]);
    expect(calls.unexpected).toEqual([]);
  });
});
