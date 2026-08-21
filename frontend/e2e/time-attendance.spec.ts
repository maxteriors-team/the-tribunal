import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { hasParallelTestUser, loginViaUI } from "./helpers";

const evidenceDir = path.resolve(process.cwd(), "../.ezcoder/eyes/out/attendance");
const seriousImpacts = new Set(["serious", "critical"]);

async function openAttendance(page: Page): Promise<void> {
  await page.goto("/time", { waitUntil: "domcontentloaded" });
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByRole("heading", { name: "Time & Attendance" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText(/This clock records timestamps and notes/i)).toBeVisible();
}

async function expectNoSeriousAxeViolations(page: Page, label: string, testInfo: TestInfo) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const violations = results.violations.filter((violation) =>
    seriousImpacts.has(violation.impact ?? ""),
  );
  await testInfo.attach(`axe-${label}.json`, {
    body: JSON.stringify({ violations, incomplete: results.incomplete }, null, 2),
    contentType: "application/json",
  });
  expect(violations).toEqual([]);
}

async function seedTechnician(page: Page): Promise<void> {
  const apiBase = "http://localhost:8000/api/v1";
  const workspacesResponse = await page.request.get(`${apiBase}/workspaces`);
  expect(workspacesResponse.ok()).toBe(true);
  const workspaces = (await workspacesResponse.json()) as Array<{ workspace: { id: string } }>;
  const workspaceId = workspaces[0]?.workspace.id;
  expect(workspaceId).toBeTruthy();

  const createResponse = await page.request.post(
    `${apiBase}/workspaces/${workspaceId}/technicians`,
    {
      data: {
        name: "Playwright Technician",
        email: `technician-${Date.now()}@example.com`,
      },
    },
  );
  expect(createResponse.status()).toBe(201);
}

async function screenshot(page: Page, name: string, testInfo: TestInfo) {
  await mkdir(evidenceDir, { recursive: true });
  const screenshotPath = path.join(evidenceDir, `${name}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true, animations: "disabled" });
  await testInfo.attach(name, { path: screenshotPath, contentType: "image/png" });
}

test.describe("authenticated Time & Attendance", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(
      !hasParallelTestUser(),
      "Configure per-worker E2E users or enable opt-in provisioning for Time & Attendance",
    );
    await loginViaUI(page, testInfo);
  });

  test("desktop clock, admin review, correction, export, and accessibility", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await openAttendance(page);

    await expect(
      page.locator('a[href="/time"]').filter({ hasText: "Time & Attendance" }).first(),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Clock in" })).toBeVisible();
    await expectNoSeriousAxeViolations(page, "attendance-desktop-clocked-out", testInfo);

    await page.getByRole("button", { name: "Clock in" }).click();
    await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
    await expect(page.getByText("Clocked in", { exact: true }).first()).toBeVisible();
    await screenshot(page, "desktop-clocked-in", testInfo);

    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
    await expect(page.getByText("Worked time is paused")).toBeVisible();
    const pausedTimer = page.locator("p.font-mono").first();
    const pausedValue = await pausedTimer.textContent();
    await page.waitForTimeout(1_100);
    await expect(pausedTimer).toHaveText(pausedValue ?? "");
    await screenshot(page, "desktop-shift-paused", testInfo);
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();

    await page.getByRole("button", { name: "Clock out" }).click();
    await expect(page.getByRole("button", { name: "Clock in" })).toBeVisible();

    await page.getByRole("tab", { name: "Team hours" }).click();
    await expect(page.getByRole("button", { name: "Add hours" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Export payroll CSV" })).toBeEnabled();
    await page.getByRole("button", { name: "Add hours" }).scrollIntoViewIfNeeded();
    await screenshot(page, "desktop-team-hours", testInfo);

    await page.getByRole("button", { name: "Edit" }).first().click();
    const dialog = page.getByRole("dialog", { name: "Correct time entry" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Save correction" })).toBeDisabled();
    await screenshot(page, "desktop-correction-dialog", testInfo);
    await dialog.getByLabel("Entry note").fill("Verified in the authenticated browser test");
    await dialog.getByLabel("Correction reason").fill("Matched the local browser evidence");
    await dialog.getByRole("button", { name: "Save correction" }).click();
    await expect(dialog).toBeHidden();

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export payroll CSV" }).click();
    const download = await downloadPromise;
    const downloadPath = path.join(evidenceDir, "attendance-payroll-export.csv");
    await download.saveAs(downloadPath);
    expect(download.suggestedFilename()).toMatch(/^attendance_raw_hours_.*\.csv$/);
    const csv = await readFile(downloadPath, "utf8");
    expect(csv).toContain("employee_id,employee_name,employee_email,work_date");
    expect(csv).toContain("gross_hours,paused_hours,total_hours");
    expect(csv).not.toContain(",open,");

    await expectNoSeriousAxeViolations(page, "attendance-desktop-team", testInfo);
    const horizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(horizontalOverflow).toBeLessThanOrEqual(1);

    await seedTechnician(page);
    await page.goto("/scorecard");
    await expect(page.getByRole("heading", { name: "Receptionist Scorecard" })).toBeVisible();
    await page.getByRole("tab", { name: "Technicians" }).click();
    await expect(page.getByRole("heading", { name: "Technician Scorecard" })).toBeVisible();
    await expect(page.getByText("Activity context—not an employee rating")).toBeVisible();
    await screenshot(page, "desktop-technician-scorecard", testInfo);
    await expectNoSeriousAxeViolations(page, "technician-scorecard-desktop", testInfo);
  });

  test("mobile layout and restricted navigation remain usable", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openAttendance(page);

    await screenshot(page, "mobile-clock", testInfo);
    await expect(page.getByRole("button", { name: "Clock in" })).toBeVisible();
    await page.getByRole("tab", { name: "Team hours" }).click();
    await expect(page.getByRole("button", { name: "Add hours" })).toBeVisible();
    await page.getByRole("button", { name: "Add hours" }).scrollIntoViewIfNeeded();
    await screenshot(page, "mobile-team-hours", testInfo);
    await expectNoSeriousAxeViolations(page, "attendance-mobile-admin", testInfo);

    await page.goto("/scorecard");
    await page.getByRole("tab", { name: "Technicians" }).click();
    await expect(page.getByRole("heading", { name: "Technician Scorecard" })).toBeVisible();
    await expect(page.getByText("Activity context—not an employee rating")).toBeVisible();
    await screenshot(page, "mobile-technician-scorecard", testInfo);
    await expectNoSeriousAxeViolations(page, "technician-scorecard-mobile", testInfo);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
    ).toBeLessThanOrEqual(1);

    await page.goto("/time");
    await openAttendance(page);
    await page.route("**/api/v1/workspaces", async (route) => {
      const response = await route.fetch();
      const workspaces = (await response.json()) as Array<Record<string, unknown>>;
      await route.fulfill({
        response,
        json: workspaces.map((workspace) => ({ ...workspace, role: "technician" })),
      });
    });
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { name: "Time & Attendance" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Clock in" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Team hours" })).toHaveCount(0);

    await page.getByRole("button", { name: "Clock in" }).click();
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
    const pausedStatus = page.getByText("Worked time is paused");
    await expect(pausedStatus).toBeVisible();
    await pausedStatus.evaluate((element) => element.scrollIntoView({ block: "center" }));
    await screenshot(page, "mobile-technician-paused", testInfo);
    await page.getByRole("button", { name: "Resume" }).click();
    await page.getByRole("button", { name: "Clock out" }).click();
    await expect(page.getByRole("button", { name: "Clock in" })).toBeVisible();

    await page.getByRole("button", { name: "Toggle Sidebar" }).click();
    const mobileSidebar = page.locator('[data-slot="sidebar"][data-mobile="true"]');
    await expect(mobileSidebar).toBeVisible();
    await expect(
      mobileSidebar.locator('a[href="/time"]').filter({ hasText: "Time & Attendance" }),
    ).toBeVisible();
    await expect(mobileSidebar.getByRole("link", { name: "Contacts" })).toHaveCount(0);
    await expect(mobileSidebar.getByRole("link", { name: "Scorecard" })).toHaveCount(0);
    await screenshot(page, "mobile-technician-navigation", testInfo);

    const horizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(horizontalOverflow).toBeLessThanOrEqual(1);
    await expectNoSeriousAxeViolations(page, "attendance-mobile-technician", testInfo);
  });
});
