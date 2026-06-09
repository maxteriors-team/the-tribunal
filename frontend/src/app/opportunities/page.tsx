import { AppSidebar } from "@/components/layout/app-sidebar";
import { OpportunitiesBoard } from "@/components/opportunities/opportunities-board";

export default function OpportunitiesRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Opportunities</h1>
          <p className="text-sm text-muted-foreground">
            Track deals across your pipeline. Drag a card or use its menu to move
            it between stages.
          </p>
        </div>
        <div className="min-h-0 flex-1 px-6 pb-6">
          <OpportunitiesBoard />
        </div>
      </div>
    </AppSidebar>
  );
}
