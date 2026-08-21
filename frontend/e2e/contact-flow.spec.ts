import { expect, test } from "@playwright/test";

import { hasParallelTestUser, loginViaUI, uniqueSuffix } from "./helpers";

/**
 * Contacts CRUD smoke test.
 *
 * Drives the contacts UI end-to-end:
 *   1. Open the "Add Contact" dialog from the contacts page.
 *   2. Create a contact with a unique first name + phone number.
 *   3. Open the contact detail, edit a field, and confirm the change.
 *   4. Delete the contact via the contact sidebar and confirm it leaves the
 *      list.
 *
 * Requires one isolated user per worker — skipped in minimal environments that
 * do not configure an account pool or opt-in provisioning.
 */

test.describe("Contacts CRUD", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(
      !hasParallelTestUser(),
      "Configure per-worker E2E users or enable opt-in provisioning for the contact flow",
    );
    await loginViaUI(page, testInfo);
  });

  test("create → edit → delete contact", async ({ page }) => {
    const suffix = uniqueSuffix();
    const firstName = `E2E-${suffix}`;
    const lastName = "Tester";
    // Reasonably unique 10-digit US-shape number derived from suffix.
    const phone = `+1555${String(Date.now()).slice(-7)}`;
    const updatedLastName = `Edited-${suffix}`;

    await page.goto("/contacts");
    await expect(page.getByRole("heading", { name: "Contacts", exact: true })).toBeVisible();

    // --- CREATE -------------------------------------------------------------
    await page
      .getByRole("button", { name: /add contact/i })
      .first()
      .click();
    const createDialog = page.getByRole("dialog", {
      name: /add new contact/i,
    });
    await expect(createDialog).toBeVisible();

    await createDialog.getByLabel(/first name/i).fill(firstName);
    await createDialog.getByLabel(/last name/i).fill(lastName);
    await createDialog.getByLabel(/phone/i).first().fill(phone);

    await createDialog.getByRole("button", { name: /create contact/i }).click();
    await expect(createDialog).toBeHidden({ timeout: 15_000 });

    // The new contact appears in the list.
    const contactRow = page.getByText(`${firstName} ${lastName}`).first();
    await expect(contactRow).toBeVisible({ timeout: 15_000 });

    // --- EDIT ---------------------------------------------------------------
    await contactRow.click();
    // Detail view must show the contact name.
    await expect(page.getByText(firstName).first()).toBeVisible();

    // The conversation quick action must open the real scheduler, not report
    // success without creating anything.
    const quickActions = page.getByTestId("contact-quick-actions");
    await quickActions.getByRole("button", { name: /^schedule$/i }).click();
    const appointmentDialog = page.getByRole("dialog", {
      name: /book appointment/i,
    });
    await expect(appointmentDialog).toBeVisible();
    await expect(appointmentDialog).toContainText(firstName);
    await appointmentDialog.getByRole("button", { name: /cancel/i }).click();
    await expect(appointmentDialog).toBeHidden();

    await page
      .getByRole("button", { name: /^edit$/i })
      .first()
      .click();
    const editDialog = page.getByRole("dialog", { name: /edit contact/i });
    await expect(editDialog).toBeVisible();

    const lastNameField = editDialog.getByLabel(/last name/i);
    await lastNameField.fill(updatedLastName);
    await editDialog.getByRole("button", { name: /save changes/i }).click();
    await expect(editDialog).toBeHidden({ timeout: 15_000 });

    await expect(page.getByText(updatedLastName).first()).toBeVisible({
      timeout: 15_000,
    });

    // --- DELETE -------------------------------------------------------------
    await page
      .getByRole("button", { name: /delete/i })
      .first()
      .click();
    const confirmDialog = page.getByRole("alertdialog");
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole("button", { name: /delete|confirm/i }).click();
    await expect(confirmDialog).toBeHidden({ timeout: 15_000 });

    // The contact name should no longer appear on the contacts list.
    await page.goto("/contacts");
    await expect(page.getByText(`${firstName} ${updatedLastName}`)).toHaveCount(0, {
      timeout: 15_000,
    });
  });
});
