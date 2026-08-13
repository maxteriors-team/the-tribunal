import { CalendarPage } from "@/components/calendar/calendar-page";
import { AppSidebar } from "@/components/layout/app-sidebar";

/**
 * The single schedule surface: appointments and field jobs on one calendar.
 *
 * `?job=<id>` opens that job's detail dialog on arrival — the landing point for
 * the convert-quote flow and for the retired `/jobs` route, which redirects here
 * carrying the parameter.
 */
export default async function Calendar({
  searchParams,
}: {
  searchParams: Promise<{ job?: string }>;
}) {
  const { job } = await searchParams;

  return (
    <AppSidebar>
      <CalendarPage key={job ?? "calendar"} initialJobId={job} />
    </AppSidebar>
  );
}
