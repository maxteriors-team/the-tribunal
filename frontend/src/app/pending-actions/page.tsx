import { AppSidebar } from "@/components/layout/app-sidebar";
import { PendingActionsPage } from "@/components/pending-actions/pending-actions-page";

export default function PendingActionsRoute() {
  return (
    <AppSidebar>
      <PendingActionsPage />
    </AppSidebar>
  );
}
