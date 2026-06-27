import { JobsCalendar } from "@/components/jobs/jobs-calendar";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default function Jobs() {
  return (
    <AppSidebar>
      <JobsCalendar />
    </AppSidebar>
  );
}
