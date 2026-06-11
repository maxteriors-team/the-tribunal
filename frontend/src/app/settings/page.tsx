import { Suspense } from "react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { SettingsPage } from "@/components/settings/settings-page";
import { PageLoadingState } from "@/components/ui/page-state";

export default function Settings() {
  return (
    <AppSidebar>
      {/* Suspense: SettingsPage reads useSearchParams (?tab=...). */}
      <Suspense fallback={<PageLoadingState />}>
        <SettingsPage />
      </Suspense>
    </AppSidebar>
  );
}
