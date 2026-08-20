import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { hasTestUser, loginViaUI } from "./helpers";

const storedAuthPath = process.env.E2E_STORAGE_STATE;
const hasStoredAuth = Boolean(storedAuthPath);
const hasAuthenticatedFixture = hasTestUser() || hasStoredAuth;

const WCAG_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const AUDITED_ROUTES = [
  "/dashboard",
  "/contacts",
  "/quotes",
  "/reports",
  "/calendar",
  "/reviews",
  "/calls",
  "/campaigns",
  "/find-leads-ai",
  "/experiments",
  "/scorecard",
  "/referral-partners",
  "/service-plans",
  "/sales-wizard",
  "/settings?tab=profile",
  "/settings?tab=proposals",
  "/settings?tab=pricing",
  "/agents/create",
  "/campaigns/sms/new",
  "/campaigns/voice/new",
  "/campaigns/pre-booking/new",
  "/experiments/new",
  "/offers/new",
] as const;

type AxeAnalysis = Awaited<ReturnType<InstanceType<typeof AxeBuilder>["analyze"]>>;

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900, theme: "dark" },
  { name: "mobile", width: 390, height: 844, theme: "dark" },
] as const;

function violationSummary(
  route: string,
  viewport: { name: string },
  violations: AxeAnalysis["violations"],
): string {
  const details = violations
    .map(
      (violation) =>
        `${violation.id} (${violation.impact ?? "unknown"}): ${violation.nodes
          .map((node) => node.target.join(" > "))
          .join(", ")}`,
    )
    .join("\n");
  return `${viewport.name} ${route} has WCAG 2.2 A/AA axe violations${details ? `:\n${details}` : ""}`;
}

async function authenticate(page: Page): Promise<void> {
  if (hasTestUser()) {
    await loginViaUI(page);
    return;
  }

  await page.goto("/contacts", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 3_000 }).catch(() => undefined);
  await page.waitForTimeout(250);
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
}

async function waitForRoute(page: Page, route: string): Promise<void> {
  await page.goto(route, { waitUntil: "domcontentloaded" });
  await page.locator("body").waitFor({ state: "visible" });
  await page.waitForLoadState("networkidle", { timeout: 3_000 }).catch(() => undefined);
  await page.waitForTimeout(250);
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
}

async function scanLightReports(page: Page, testInfo: TestInfo): Promise<void> {
  await page.evaluate(() => localStorage.setItem("theme", "light"));
  await waitForRoute(page, "/reports");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(250);

  const results = await new AxeBuilder({ page })
    .include('[aria-labelledby="reports-heading"]')
    .withTags(WCAG_AA_TAGS)
    .analyze();
  const viewport = { ...VIEWPORTS[0], name: "desktop-light" };

  await testInfo.attach("axe-desktop-light-reports-financial.json", {
    body: JSON.stringify(
      {
        route: "/reports",
        viewport,
        violations: results.violations,
        incomplete: results.incomplete,
      },
      null,
      2,
    ),
    contentType: "application/json",
  });
  expect
    .soft(results.violations, violationSummary("/reports", viewport, results.violations))
    .toEqual([]);
}

async function scanRoute(
  page: Page,
  route: string,
  viewport: (typeof VIEWPORTS)[number],
  testInfo: TestInfo,
): Promise<void> {
  await waitForRoute(page, route);
  const results = await new AxeBuilder({ page }).withTags(WCAG_AA_TAGS).analyze();

  await testInfo.attach(
    `axe-${viewport.name}-${route.replaceAll(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "")}.json`,
    {
      body: JSON.stringify(
        {
          route,
          viewport,
          violations: results.violations,
          incomplete: results.incomplete,
        },
        null,
        2,
      ),
      contentType: "application/json",
    },
  );

  expect
    .soft(results.violations, violationSummary(route, viewport, results.violations))
    .toEqual([]);
}

test.afterEach(async ({ context }) => {
  if (storedAuthPath) {
    await context.storageState({ path: storedAuthPath });
  }
});

test.describe("WCAG 2.2 AA route regression", () => {
  test.skip(
    !hasAuthenticatedFixture,
    "Set E2E credentials or E2E_STORAGE_STATE to scan authenticated routes.",
  );

  for (const viewport of VIEWPORTS) {
    test(`${viewport.name} CRM routes have no axe violations`, async ({ page }, testInfo) => {
      test.setTimeout(180_000);
      await page.setViewportSize(viewport);
      await authenticate(page);
      await page.evaluate((theme) => localStorage.setItem("theme", theme), viewport.theme);
      await page.reload({ waitUntil: "domcontentloaded" });

      for (const route of AUDITED_ROUTES) {
        await scanRoute(page, route, viewport, testInfo);
      }

      if (viewport.name === "desktop") {
        await scanLightReports(page, testInfo);
      }
    });
  }
});

test.describe("keyboard-only CRM regression", () => {
  test.skip(
    !hasAuthenticatedFixture,
    "Set E2E credentials or E2E_STORAGE_STATE to run keyboard checks.",
  );

  test("mobile Settings tabs keep names and arrow-key navigation", async ({ page }) => {
    await page.setViewportSize(VIEWPORTS[1]);
    await authenticate(page);
    await waitForRoute(page, "/settings?tab=profile");

    const tabList = page.getByRole("tablist", { name: "Settings sections" });
    const tabs = tabList.getByRole("tab");
    expect(await tabs.count()).toBeGreaterThan(5);

    for (let index = 0; index < (await tabs.count()); index += 1) {
      await expect(tabs.nth(index)).toHaveAccessibleName(/\S+/);
    }

    await tabs.first().focus();
    await page.keyboard.press("ArrowRight");
    await expect(tabs.nth(1)).toBeFocused();
    await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
  });

  test("campaign, agent, and offer steppers expose keyboard state", async ({ page }) => {
    await page.setViewportSize(VIEWPORTS[1]);
    await authenticate(page);

    for (const scenario of [
      { route: "/campaigns/sms/new", navigationName: "Setup progress" },
      { route: "/agents/create", navigationName: "Agent setup progress" },
      { route: "/offers/new", navigationName: "Offer setup progress" },
    ]) {
      await waitForRoute(page, scenario.route);
      const navigation = page.getByRole("navigation", { name: scenario.navigationName });
      await expect(navigation).toBeVisible();
      const stepButtons = navigation.getByRole("button");
      expect(await stepButtons.count()).toBeGreaterThan(1);

      for (let index = 0; index < (await stepButtons.count()); index += 1) {
        await expect(stepButtons.nth(index)).toHaveAccessibleName(/^Step \d+:/);
      }

      const currentStep = navigation.locator('[aria-current="step"]');
      await expect(currentStep).toHaveCount(1);
      await currentStep.focus();
      await expect(currentStep).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(currentStep).toHaveAttribute("aria-current", "step");
    }
  });

  test("report scroll region receives and retains keyboard focus", async ({ page }) => {
    await page.setViewportSize(VIEWPORTS[1]);
    await authenticate(page);
    await waitForRoute(page, "/reports");

    const reports = page.getByRole("region", { name: "Reports" });
    await reports.focus();
    await expect(reports).toBeFocused();
    await page.keyboard.press("PageDown");
    await expect(reports).toBeFocused();
  });
});
