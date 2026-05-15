import { AppSidebar } from "@/components/layout/app-sidebar";
import { PhoneNumbersTable } from "@/components/settings/phone-numbers-table";

export default function PhoneNumbers() {
  return (
    <AppSidebar>
      <PhoneNumbersTable variant="page" />
    </AppSidebar>
  );
}
