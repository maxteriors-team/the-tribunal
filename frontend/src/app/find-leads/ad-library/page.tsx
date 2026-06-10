import { AppSidebar } from "@/components/layout/app-sidebar";

import { AdLibraryClient } from "./ad-library-client";

export default function AdLibrary() {
  return (
    <AppSidebar>
      <AdLibraryClient />
    </AppSidebar>
  );
}
