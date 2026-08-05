import { AppSidebar } from "@/components/layout/app-sidebar";
import { SalesPerformanceReport } from "@/components/reports/sales-performance-report";

export default function SalesPerformanceRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            Sales Performance
          </h1>
          <p className="text-sm text-muted-foreground">
            The funnel and the money: who converts, who turns up, what closes,
            and what it was worth — so you can see where the leak is, not just
            what you sold.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <SalesPerformanceReport />
        </div>
      </div>
    </AppSidebar>
  );
}
