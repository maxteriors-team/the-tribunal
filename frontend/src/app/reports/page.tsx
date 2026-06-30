import { AppSidebar } from "@/components/layout/app-sidebar";
import { ReportsOverview } from "@/components/reports/reports-overview";

export default function ReportsRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Reports</h1>
          <p className="text-sm text-muted-foreground">
            Accounts-receivable aging and job profitability at a glance.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <ReportsOverview />
        </div>
      </div>
    </AppSidebar>
  );
}
