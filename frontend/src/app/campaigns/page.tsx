import { AppSidebar } from "@/components/layout/app-sidebar";
import { CampaignsClient } from "./campaigns-client";

export default function CampaignsPage() {
  return (
    <AppSidebar>
      <CampaignsClient />
    </AppSidebar>
  );
}
