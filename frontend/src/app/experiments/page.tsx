import { AppSidebar } from "@/components/layout/app-sidebar";
import { ExperimentsClient } from "./experiments-client";

export default function ExperimentsPage() {
  return (
    <AppSidebar>
      <ExperimentsClient />
    </AppSidebar>
  );
}
