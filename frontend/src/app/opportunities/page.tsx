import { OpportunitiesClient } from "./opportunities-client";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default function Page() {
  return (
    <AppSidebar>
      <div className="h-full overflow-hidden">
        <OpportunitiesClient />
      </div>
    </AppSidebar>
  );
}
