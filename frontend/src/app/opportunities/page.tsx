import { AppSidebar } from "@/components/layout/app-sidebar";
import { OpportunitiesBoard } from "@/components/opportunities/opportunities-board";

export default function OpportunitiesRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full min-h-full min-w-0 flex-col">
        <div className="shrink-0 p-4 pb-3 sm:p-6 sm:pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Opportunities</h1>
          <p className="text-sm text-muted-foreground">
            Track deals across your pipeline. Drag a card or use its menu to move it between stages.
          </p>
        </div>
        <div className="min-h-[20rem] min-w-0 flex-1 px-4 pb-4 sm:px-6 sm:pb-6">
          <OpportunitiesBoard />
        </div>
      </div>
    </AppSidebar>
  );
}
