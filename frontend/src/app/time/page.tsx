import { AppSidebar } from "@/components/layout/app-sidebar";
import { TimeAttendancePage } from "@/components/time/time-attendance-page";

export default function TimeAttendanceRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="border-b px-4 py-5 sm:px-6">
          <h1 className="text-2xl font-semibold tracking-tight">Time &amp; Attendance</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Record shifts, review worked hours, and prepare payroll time exports.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          <TimeAttendancePage />
        </div>
      </div>
    </AppSidebar>
  );
}
