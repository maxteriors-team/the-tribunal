import { formatPhoneNumber } from "./phone";

/**
 * Display label for a contact.
 *
 * Some contacts genuinely have no name: an imported or inbound conversation
 * may only identify the customer's number. Blank is the honest value to *store*
 * because `first_name` feeds SMS and AI personalisation, so a placeholder would
 * text customers "Hi (555) 123-4567". Only the display needs a fallback, so
 * the phone number is used here: it is something an operator can act on.
 */
export function contactDisplayName(contact: {
  first_name?: string | null;
  last_name?: string | null;
  phone_number?: string | null;
}): string {
  const name = [contact.first_name, contact.last_name]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(" ");
  return name || formatPhoneNumber(contact.phone_number) || "Unknown";
}
