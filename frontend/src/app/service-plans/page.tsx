import { AppSidebar } from "@/components/layout/app-sidebar";
import { ServicePlansList } from "@/components/service-plans/service-plans-list";

export default function ServicePlansRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full min-w-0 flex-col overflow-hidden">
        <div className="p-4 pb-3 sm:p-6 sm:pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Service Plans</h1>
          <p className="text-sm text-muted-foreground">
            Everyone signed up for recurring work — lighting Care Plans and Christmas light seasons.
            Plans are created automatically when a client approves their proposal, and each one puts
            its next visit on the schedule.
          </p>
        </div>
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 pb-4 sm:px-6 sm:pb-6">
          <ServicePlansList />
        </div>
      </div>
    </AppSidebar>
  );
}
