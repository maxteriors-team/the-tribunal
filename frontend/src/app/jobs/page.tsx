import { JobsCalendar } from "@/components/jobs/jobs-calendar";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default async function Jobs({
  searchParams,
}: {
  searchParams: Promise<{ job?: string }>;
}) {
  const { job } = await searchParams;

  return (
    <AppSidebar>
      <JobsCalendar key={job ?? "jobs"} initialJobId={job} />
    </AppSidebar>
  );
}
