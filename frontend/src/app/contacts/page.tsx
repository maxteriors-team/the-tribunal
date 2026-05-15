import * as React from "react";
import { ContactsPage } from "@/components/contacts/contacts-page";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default function Home() {
  return (
    <AppSidebar>
      <div className="h-full overflow-hidden">
        <React.Suspense fallback={null}>
          <ContactsPage />
        </React.Suspense>
      </div>
    </AppSidebar>
  );
}
