import { redirect } from "next/navigation";

// Sales Wizard is consolidated into the Quotes & Estimates designer. Keep the
// legacy route so existing bookmarks and customer workflows do not dead-end.
export default function SalesWizardRoute() {
  redirect("/quotes?tab=designer");
}
