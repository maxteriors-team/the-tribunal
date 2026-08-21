import { expect, test, type Locator, type Page } from "@playwright/test";

import { hasParallelTestUser, loginViaUI } from "./helpers";

async function createCustomer(
  page: Page,
  customer: { firstName: string; lastName: string; phone: string },
) {
  await page.getByRole("button", { name: "Add Contact" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("First Name").fill(customer.firstName);
  await dialog.getByLabel("Last Name").fill(customer.lastName);
  await dialog.getByLabel("Phone").fill(customer.phone);
  await dialog.getByRole("button", { name: "Create Contact" }).click();
  await expect(page.getByText("Contact created").last()).toBeVisible();
}

async function selectCustomer(page: Page, picker: Locator, customerName: string) {
  await picker.fill(customerName);
  const option = page.getByRole("option").filter({ hasText: customerName }).first();
  await expect(option).toBeVisible();
  await option.click();
}

function opportunityCard(page: Page, opportunityName: string) {
  return page.locator('[data-testid^="opportunity-card-"]').filter({ hasText: opportunityName });
}

test("creates, relinks, displays, and filters an opportunity by customer", async ({
  page,
}, testInfo) => {
  test.skip(
    !hasParallelTestUser(),
    "Configure per-worker E2E users or enable opt-in provisioning for the opportunity flow",
  );
  await loginViaUI(page, testInfo);

  await page.goto("/contacts");
  await page.waitForURL(/\/onboarding$/, { timeout: 5_000 }).catch(() => undefined);
  if (/\/onboarding$/.test(page.url())) {
    await page.getByRole("button", { name: /skip for now/i }).click();
    await expect(page).not.toHaveURL(/\/onboarding$/, { timeout: 15_000 });
  }

  const runId = Date.now().toString().slice(-7);
  const firstCustomer = {
    firstName: `Avery${runId}`,
    lastName: "Opportunity",
    phone: `512${runId}`,
  };
  const secondCustomer = {
    firstName: `Blair${runId}`,
    lastName: "Opportunity",
    phone: `513${runId}`,
  };
  const firstCustomerName = `${firstCustomer.firstName} ${firstCustomer.lastName}`;
  const secondCustomerName = `${secondCustomer.firstName} ${secondCustomer.lastName}`;
  const opportunityName = `E2E customer deal ${runId}`;

  await page.goto("/contacts");
  await expect(
    page.getByRole("heading", { name: "Contacts", exact: true }),
  ).toBeVisible();
  await createCustomer(page, firstCustomer);
  await createCustomer(page, secondCustomer);

  await page.goto("/opportunities");
  await page.getByTestId("add-opportunity").click();

  const createSheet = page.getByRole("dialog").filter({ hasText: "Add Opportunity" });
  await expect(
    createSheet.getByText("Required. Add new customers from Contacts first."),
  ).toBeVisible();
  const createCustomerPicker = createSheet.getByRole("combobox", {
    name: /Customer/,
  });
  await expect(createCustomerPicker).toHaveAttribute("required", "");
  await selectCustomer(page, createCustomerPicker, firstCustomerName);
  await createSheet.getByLabel("Name *").fill(opportunityName);
  await createSheet.getByLabel("Amount").fill("2750");
  await createSheet.getByRole("button", { name: "Create Opportunity" }).click();
  await expect(page.getByText("Opportunity created")).toBeVisible();

  let card = opportunityCard(page, opportunityName);
  await expect(card).toContainText(firstCustomerName);

  await card.locator("button").first().click();
  const detailSheet = page.getByRole("dialog").filter({ hasText: opportunityName });
  const detailCustomerPicker = detailSheet.getByRole("combobox", { name: "Customer" });
  await expect(detailCustomerPicker).toHaveValue(firstCustomerName);

  await selectCustomer(page, detailCustomerPicker, secondCustomerName);
  await detailSheet.getByRole("button", { name: "Save customer" }).click();
  await expect(page.getByText(`Customer changed to ${secondCustomerName}`)).toBeVisible();
  await detailSheet.getByRole("button", { name: "Close" }).click();

  card = opportunityCard(page, opportunityName);
  await expect(card).toContainText(secondCustomerName);

  const filterPicker = page.getByRole("combobox", { name: "Filter by customer" });
  await selectCustomer(page, filterPicker, firstCustomerName);
  await expect(opportunityCard(page, opportunityName)).toHaveCount(0);

  await selectCustomer(page, filterPicker, secondCustomerName);
  card = opportunityCard(page, opportunityName);
  await expect(card).toContainText(secondCustomerName);

  await card.getByRole("button", { name: `Actions for ${opportunityName}` }).click();
  await page.getByRole("menuitem", { name: "Remove from pipeline" }).click();
  await page.getByRole("button", { name: "Remove from pipeline" }).click();
  await expect(page.getByText("Removed from the pipeline")).toBeVisible();
});
