import { AppSidebar } from "@/components/layout/app-sidebar";
import { OfferBuilderClient } from "./offer-builder-client";

export default function CreateOfferPage() {
  return (
    <AppSidebar>
      <div className="p-6 max-w-4xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Create Offer</h1>
          <p className="text-muted-foreground">
            Build an irresistible offer with value stacking
          </p>
        </div>
        <OfferBuilderClient />
      </div>
    </AppSidebar>
  );
}
