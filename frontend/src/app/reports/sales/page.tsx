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
            Average job value, attach rate, and close rate: the three levers that
            grow revenue without buying more leads.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <SalesPerformanceReport />
        </div>
      </div>
    </AppSidebar>
  );
}
