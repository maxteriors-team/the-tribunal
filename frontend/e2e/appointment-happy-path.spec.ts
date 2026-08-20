import { expect, test, type Page } from "@playwright/test";

import { hasParallelTestUser, loginViaUI, uniqueSuffix } from "./helpers";

/**
 * Full "book someone onto the schedule" happy path.
 *
 * `appointment.spec.ts` deliberately stops at validation because it cannot
 * guarantee a bookable contact exists. This spec closes that gap by driving
 * every click an operator makes: pick a contact, pick a date, pick a time,
 * set duration/agent/service type, submit, and then confirm the booking is
 * really on the calendar (month grid chip + Today/Upcoming sidebar) and that
 * it survives a reload — i.e. it was persisted, not just optimistically
 * rendered.
 *
 * Account strategy: every parallel worker gets its own pre-provisioned account
 * or an opt-in throwaway account, so refresh-token rotation cannot cross workers.
 */

/** react-day-picker labels each day button like "Tuesday, August 11th, 2026". */
function dayPickerLabel(date: Date): string {
  const weekday = date.toLocaleDateString("en-US", { weekday: "long" });
  const month = date.toLocaleDateString("en-US", { month: "long" });
  const day = date.getDate();
  const rem100 = day % 100;
  const suffix =
    rem100 >= 11 && rem100 <= 13
      ? "th"
      : (({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[day % 10] ?? "th");
  return `${weekday}, ${month} ${day}${suffix}, ${date.getFullYear()}`;
}

interface CreatedApiResource {
  id: number;
  collectionUrl: string;
}

interface CreatedContact extends CreatedApiResource {
  fullName: string;
  /** Contact search ILIKEs each column separately, so only a single-column
   *  term (last name) matches server-side — a full name never does. */
  lastName: string;
}

/** Create a bookable contact through the contacts UI. */
async function createContact(page: Page): Promise<CreatedContact> {
  const suffix = uniqueSuffix();
  const firstName = "Booked";
  const lastName = `Customer-${suffix}`;

  await page.goto("/contacts");
  const addContact = page.getByRole("button", { name: /add contact/i });
  await expect(addContact).toBeVisible({ timeout: 20_000 });
  await addContact.click();

  const dialog = page.getByRole("dialog", { name: /add new contact/i });
  await expect(dialog).toBeVisible();

  await dialog.getByLabel(/first name/i).fill(firstName);
  await dialog.getByLabel(/last name/i).fill(lastName);
  // Unique-ish number so reruns don't collide on the phone uniqueness rule.
  const phoneTail = Date.now().toString().slice(-7);
  await dialog.getByLabel(/phone number/i).fill(`+1555${phoneTail}`);

  const createResponsePromise = page.waitForResponse(
    (response) =>
      /\/contacts\/manual$/.test(response.url()) && response.request().method() === "POST",
    { timeout: 20_000 },
  );
  await dialog.getByRole("button", { name: /^create contact$/i }).click();
  const response = await createResponsePromise;
  expect(response.status(), "contact POST should succeed").toBeLessThan(300);
  const contact = (await response.json()) as { id: number };
  await expect(dialog).toBeHidden({ timeout: 15_000 });

  return {
    id: contact.id,
    collectionUrl: response.url().replace(/\/manual$/, ""),
    fullName: `${firstName} ${lastName}`,
    lastName,
  };
}

test.describe("Calendar — book a contact onto the schedule", () => {
  let appointmentToDelete: CreatedApiResource | null = null;
  let contactToDelete: CreatedApiResource | null = null;

  test.beforeEach(async ({ page }, testInfo) => {
    appointmentToDelete = null;
    contactToDelete = null;
    test.skip(
      !hasParallelTestUser(),
      "Configure per-worker E2E users or enable opt-in provisioning for the booking flow",
    );
    await loginViaUI(page, testInfo);
  });

  test.afterEach(async ({ page }) => {
    for (const resource of [appointmentToDelete, contactToDelete]) {
      if (!resource) continue;
      const response = await page.request.delete(`${resource.collectionUrl}/${resource.id}`);
      expect(response.status(), `cleanup DELETE ${resource.collectionUrl}`).toBe(204);
    }
  });

  test("books an appointment and shows it on the calendar", async ({ page }) => {
    // Registration + contact creation + booking + reload is a long flow.
    test.setTimeout(120_000);

    const contact = await createContact(page);
    contactToDelete = contact;
    const { fullName: contactName, lastName } = contact;

    // Step 1 — open the scheduler.
    await page.goto("/calendar");
    await expect(page.getByRole("heading", { name: "Calendar" })).toBeVisible();

    // Step 2 — open the New Appointment dialog.
    await page.getByRole("button", { name: /new appointment/i }).click();
    const dialog = page.getByRole("dialog", { name: /new appointment/i });
    await expect(dialog).toBeVisible();

    // Step 3 — search for and select the contact.
    await dialog.getByPlaceholder(/search contacts/i).fill(lastName);
    const contactSelect = dialog.getByRole("combobox").first();
    await expect(contactSelect).toBeEnabled({ timeout: 15_000 });
    await contactSelect.click();

    const contactOption = page.getByRole("option", {
      name: new RegExp(lastName, "i"),
    });
    await expect(contactOption).toBeVisible({ timeout: 15_000 });
    await contactOption.click();

    // Step 4 — pick a date. The trigger's accessible name comes from its
    // <label> ("Date *"), not its text, so match on the visible text instead.
    // Book tomorrow: always enabled (past days are disabled) and always a
    // future slot regardless of what time of day the suite runs.
    await dialog.locator('button:has-text("Pick a date")').click();

    // The grid must be mounted before counting: `count()` does not auto-wait,
    // so checking too early reports 0 days and falsely trips the fallback.
    const dayGrid = page.locator(".rdp-root");
    await expect(dayGrid).toBeVisible({ timeout: 10_000 });

    const target = new Date();
    target.setDate(target.getDate() + 1);
    let dayButton = page.getByRole("button", { name: dayPickerLabel(target) });
    if ((await dayButton.count()) === 0) {
      // Tomorrow can fall outside the rendered grid at a month boundary. The
      // nav arrows are absolutely positioned under the caption, so a plain
      // click fails actionability — force it.
      await page.getByRole("button", { name: /go to the next month/i }).click({ force: true });
      dayButton = page.getByRole("button", { name: dayPickerLabel(target) });
    }
    await expect(dayButton).toBeEnabled({ timeout: 10_000 });
    await dayButton.click();

    // The trigger now shows the chosen date instead of the placeholder.
    await expect(dialog.locator('button:has-text("Pick a date")')).toHaveCount(0);

    // The popover does not close itself on selection, and while open it covers
    // the fields below it, so dismiss it before continuing.
    await page.keyboard.press("Escape");
    await expect(dayGrid).toBeHidden({ timeout: 5_000 });

    // Step 5 — pick a time slot. The UI exposes localized 12-hour labels.
    const timeSelect = dialog.getByRole("combobox").nth(1);
    await timeSelect.click();
    await page.getByRole("option", { name: "2:00 PM", exact: true }).click();

    // Step 6 — set the duration.
    const durationSelect = dialog.getByRole("combobox").nth(2);
    await durationSelect.click();
    await page.getByRole("option", { name: /^1 hour$/i }).click();

    // Step 6b — assigned agent. Left as "No agent" on purpose: picking an
    // agent arms automated SMS reminders, which we don't want a test to fire.
    const agentSelect = dialog.getByRole("combobox").nth(3);
    await agentSelect.click();
    await page.getByRole("option", { name: /^no agent$/i }).click();

    // Step 7 — service type is what renders on the calendar chip, so it is the
    // marker we assert on afterwards.
    const serviceType = `Roof Wash ${uniqueSuffix().slice(0, 6)}`;
    await dialog.getByLabel(/service type/i).fill(serviceType);
    await dialog.getByLabel(/notes/i).fill("Booked by the automated happy-path check.");

    // Step 8 — submit and wait for the real POST to succeed.
    const createResponse = page.waitForResponse(
      (res) => /\/appointments/.test(res.url()) && res.request().method() === "POST",
      { timeout: 20_000 },
    );
    await dialog.getByRole("button", { name: /^schedule$/i }).click();

    const response = await createResponse;
    expect(response.status(), "appointment POST should succeed").toBeLessThan(300);
    const appointment = (await response.json()) as { id: number };
    appointmentToDelete = { id: appointment.id, collectionUrl: response.url() };

    // Step 9 — the dialog closes on success.
    await expect(dialog).toBeHidden({ timeout: 15_000 });

    // Step 10 — the booking is on the month grid and in the Upcoming list.
    await expect(
      page.getByRole("button", { name: new RegExp(serviceType, "i") }).first(),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(contactName).first()).toBeVisible();

    // Step 11 — reload to prove it was persisted server-side, then open the
    // details dialog the way an operator would confirm the booking.
    await page.reload();
    await expect(page.getByRole("heading", { name: "Calendar" })).toBeVisible();

    const chip = page.getByRole("button", { name: new RegExp(serviceType, "i") }).first();
    await expect(chip).toBeVisible({ timeout: 15_000 });
    await chip.click();

    const details = page.getByRole("dialog", { name: new RegExp(serviceType, "i") });
    await expect(details).toBeVisible();
    await expect(details.getByText(new RegExp(contactName, "i")).first()).toBeVisible();
    await expect(details.getByText(/scheduled/i).first()).toBeVisible();
  });
});
