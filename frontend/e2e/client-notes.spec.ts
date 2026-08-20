import { expect, test, type Page } from "@playwright/test";

import { uniqueSuffix } from "./helpers";

const PASSWORD = "E2ePassw0rd!test";

async function provisionOperator(page: Page) {
  const email = `e2e-client-notes-${uniqueSuffix()}@example.com`;
  await page.goto("/register");
  await page.getByLabel(/full name/i).fill("Client Notes E2E");
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

test("creates a client with notes", async ({ page }) => {
  test.setTimeout(120_000);
  await provisionOperator(page);
  await page.goto("/contacts");
  await page
    .getByRole("button", { name: /add contact/i })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: /add new contact/i });
  await dialog.getByLabel(/first name/i).fill("Notes");
  const lastName = `Client-${uniqueSuffix()}`;
  await dialog.getByLabel(/last name/i).fill(lastName);
  await dialog.getByLabel(/phone number/i).fill(`+1555${Date.now().toString().slice(-7)}`);
  await dialog.getByLabel("Notes").fill("Gate code 4821. Call before arrival.");
  const responsePromise = page.waitForResponse(
    (response) =>
      /\/contacts\/manual$/.test(response.url()) && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: /^create contact$/i }).click();
  const response = await responsePromise;
  expect(response.ok(), await response.text()).toBeTruthy();
  await expect(dialog).toBeHidden();
  await page.getByText(`Notes ${lastName}`, { exact: false }).first().click();
  await page.getByRole("button", { name: "Notes", exact: true }).click();
  let noteDialog = page.getByRole("dialog", { name: "Add client note" });
  await noteDialog.getByLabel("Note").fill("Sidebar note: prefers morning appointments.");
  let noteResponsePromise = page.waitForResponse(
    (noteResponse) =>
      /\/contacts\/\d+\/notes$/.test(noteResponse.url()) &&
      noteResponse.request().method() === "POST",
  );
  await noteDialog.getByRole("button", { name: "Save note" }).click();
  let noteResponse = await noteResponsePromise;
  expect(noteResponse.ok(), await noteResponse.text()).toBeTruthy();
  await expect(noteDialog).toBeHidden();

  await page.getByRole("button", { name: "Notes", exact: true }).click();
  await expect(noteDialog.getByLabel("Note")).toHaveValue("");
  await noteDialog.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("button", { name: "Conversation actions" }).click();
  await page.getByRole("menuitem", { name: "Add note" }).click();
  noteDialog = page.getByRole("dialog", { name: "Add client note" });
  await noteDialog.getByLabel("Note").fill("Conversation note: send estimate by email.");
  noteResponsePromise = page.waitForResponse(
    (noteResponse) =>
      /\/contacts\/\d+\/notes$/.test(noteResponse.url()) &&
      noteResponse.request().method() === "POST",
  );
  await noteDialog.getByRole("button", { name: "Save note" }).click();
  noteResponse = await noteResponsePromise;
  expect(noteResponse.ok(), await noteResponse.text()).toBeTruthy();
  await expect(noteDialog).toBeHidden();

  await page.getByRole("link", { name: "Details & history" }).click();
  await expect(page.getByRole("heading", { name: "Contact Info" })).toBeVisible();
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "Notes", exact: true }).click();
  noteDialog = page.getByRole("dialog", { name: "Add client note" });
  await noteDialog.getByLabel("Note").fill("Detail note: dog is friendly.");
  noteResponsePromise = page.waitForResponse(
    (noteResponse) =>
      /\/contacts\/\d+\/notes$/.test(noteResponse.url()) &&
      noteResponse.request().method() === "POST",
  );
  await noteDialog.getByRole("button", { name: "Save note" }).click();
  noteResponse = await noteResponsePromise;
  expect(noteResponse.ok(), await noteResponse.text()).toBeTruthy();
  await expect(noteDialog).toBeHidden();
  const notesContent = page.locator("p.whitespace-pre-wrap");
  await expect(notesContent).toContainText("Gate code 4821. Call before arrival.");
  await expect(notesContent).toContainText("Sidebar note: prefers morning appointments.");
  await expect(notesContent).toContainText("Conversation note: send estimate by email.");
  await expect(notesContent).toContainText("Detail note: dog is friendly.");
  await page.screenshot({ path: ".ezcoder/screenshots/client-notes.png", fullPage: true });
});
