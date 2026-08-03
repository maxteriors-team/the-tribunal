import { InventoryList } from "@/components/inventory/inventory-list";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default function InventoryRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Inventory</h1>
          <p className="text-sm text-muted-foreground">
            What is on hand, what needs reordering, and what each job consumed.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <InventoryList />
        </div>
      </div>
    </AppSidebar>
  );
}
