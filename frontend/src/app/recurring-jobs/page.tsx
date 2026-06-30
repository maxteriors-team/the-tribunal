import { AppSidebar } from "@/components/layout/app-sidebar";
import { RecurringJobsList } from "@/components/recurring-jobs/recurring-jobs-list";

export default function RecurringJobsRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Recurring Jobs</h1>
          <p className="text-sm text-muted-foreground">
            Maintenance contracts that auto-generate a scheduled job on a
            recurring basis.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <RecurringJobsList />
        </div>
      </div>
    </AppSidebar>
  );
}
