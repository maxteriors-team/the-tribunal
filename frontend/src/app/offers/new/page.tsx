import { AppSidebar } from "@/components/layout/app-sidebar";

import { OfferBuilderClient } from "./offer-builder-client";

export default function CreateOfferPage() {
  return (
    <AppSidebar>
      <div className="mx-auto max-w-4xl p-4 sm:p-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Create Offer</h1>
          <p className="text-muted-foreground">Build an irresistible offer with value stacking</p>
        </div>
        <OfferBuilderClient />
      </div>
    </AppSidebar>
  );
}
