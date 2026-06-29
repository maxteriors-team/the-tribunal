import { CatalogList } from "@/components/catalog/catalog-list";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default function CatalogRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Price Book</h1>
          <p className="text-sm text-muted-foreground">
            Reusable services and products that autofill name and price on quotes
            and invoices.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <CatalogList />
        </div>
      </div>
    </AppSidebar>
  );
}
