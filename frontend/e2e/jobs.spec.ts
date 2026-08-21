import { expect, test, type Page } from "@playwright/test";

import { canProvisionUsers, uniqueSuffix } from "./helpers";

const PASSWORD = "E2ePassw0rd!test";

async function provisionOperator(page: Page) {
  const email = `e2e-jobs-${uniqueSuffix()}@example.com`;
  await page.goto("/register");
  await page.getByLabel(/full name/i).fill("Jobs E2E");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /create account|sign up|register/i }).click();
  await expect(page).not.toHaveURL(/\/register$/, { timeout: 20_000 });
  await page.goto("/contacts");
  await page.waitForURL(/\/onboarding/, { timeout: 10_000 }).catch(() => undefined);
  if (/\/onboarding/.test(page.url())) {
    await page.getByRole("button", { name: /skip for now/i }).click();
    await expect(page).not.toHaveURL(/\/onboarding/, { timeout: 15_000 });
  }
}

async function createContact(page: Page) {
  const suffix = uniqueSuffix();
  const lastName = `Jobs-${suffix}`;
  await page.goto("/contacts");
  await page
    .getByRole("button", { name: /add contact/i })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: /add new contact/i });
  await dialog.getByLabel(/first name/i).fill("Morgan");
  await dialog.getByLabel(/last name/i).fill(lastName);
  await dialog.getByLabel(/phone number/i).fill(`+1555${Date.now().toString().slice(-7)}`);
  const responsePromise = page.waitForResponse(
    (response) =>
      /\/contacts\/manual$/.test(response.url()) && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: /^create contact$/i }).click();
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
  return { lastName, fullName: `Morgan ${lastName}` };
}

test("creates, filters, opens, and updates a job", async ({ page }) => {
  test.skip(
    !canProvisionUsers(),
    "Set E2E_ALLOW_PROVISIONING=1 to create an isolated workspace for the jobs flow",
  );
  test.setTimeout(120_000);
  await provisionOperator(page);
  const contact = await createContact(page);

  await page.goto("/jobs");
  await expect(page.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "All jobs" })).toBeVisible();

  await page.getByRole("button", { name: /new job/i }).click();
  const dialog = page.getByRole("dialog", { name: /new job/i });
  await dialog.getByLabel("Customer").click();
  await dialog.getByLabel("Customer").fill(contact.lastName);
  await page.getByText(contact.fullName, { exact: false }).click();
  await dialog.getByLabel("Title").fill("E2E landscape lighting service");
  await dialog.getByLabel("Schedule later").click();
  await dialog.getByLabel("Visit instructions").fill("Test the transformer and all fixtures.");
  const createPromise = page.waitForResponse(
    (response) => /\/jobs$/.test(response.url()) && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: /^save job$/i }).click();
  const createResponse = await createPromise;
  expect(createResponse.ok(), await createResponse.text()).toBeTruthy();
  await expect(dialog).toBeHidden();

  await page.getByLabel("Search jobs").fill("E2E landscape");
  const jobButton = page.getByRole("button", { name: "E2E landscape lighting service" });
  await expect(jobButton).toBeVisible();
  await jobButton.click();
  const detail = page.getByRole("dialog", { name: /E2E landscape lighting service/i });
  await expect(detail).toContainText(contact.fullName);

  await detail.getByRole("tab", { name: "Visits & pricing" }).click();
  await detail.getByRole("button", { name: "Add visit" }).click();
  await detail.getByLabel("Starts").fill("2030-01-15T09:00");
  await detail.getByLabel("Ends").fill("2030-01-15T10:30");
  await detail.getByLabel("Visit instructions").fill("Confirm transformer load before install.");
  const visitPromise = page.waitForResponse(
    (response) => /\/visits$/.test(response.url()) && response.request().method() === "POST",
  );
  await detail.getByRole("button", { name: "Save visit" }).click();
  expect((await visitPromise).ok()).toBeTruthy();
  await expect(detail).toContainText("Jan 15, 2030");

  await detail.getByRole("button", { name: "Add line" }).click();
  await detail.getByLabel("Line 1 name").fill("Landscape lighting service");
  await detail.getByLabel("Line 1 quantity").fill("2");
  await detail.getByLabel("Line 1 unit price").fill("125");
  await detail.getByLabel("Tax rate (%)").fill("6");
  const pricingPromise = page.waitForResponse(
    (response) => /\/pricing$/.test(response.url()) && response.request().method() === "PUT",
  );
  await detail.getByRole("button", { name: "Save pricing" }).click();
  expect((await pricingPromise).ok()).toBeTruthy();
  await expect(detail).toContainText("$265.00");
  await page.screenshot({ path: ".ezcoder/screenshots/job-visits-pricing-desktop.png" });

  await detail.getByRole("tab", { name: "Dispatch" }).click();
  const statusSelect = detail.getByRole("combobox", { name: "Status" });
  await expect(statusSelect).toContainText("Scheduled");
  await statusSelect.click();
  await page.getByRole("option", { name: "In progress", exact: true }).click();
  await expect(page.getByText("Status updated")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByLabel("Filter by status").click();
  await page.getByRole("option", { name: "In progress", exact: true }).click();
  await expect(jobButton).toBeVisible();
  await page.getByText("Status updated").waitFor({ state: "hidden" });
  await page.screenshot({ path: ".ezcoder/screenshots/jobs-desktop.png", fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await jobButton.scrollIntoViewIfNeeded();
  await page.screenshot({ path: ".ezcoder/screenshots/jobs-mobile.png" });
});
