import { redirect } from "next/navigation";

/**
 * `/jobs` was a second, job-only calendar. The schedule is now one surface, so
 * this route redirects to `/calendar`.
 *
 * The `?job=<id>` deep link is carried across: converting an approved quote
 * lands the user straight on the job it just created, and that link also exists
 * in already-sent notifications, so dropping the parameter would strand people
 * on a calendar with nothing open.
 */
export default async function Jobs({
  searchParams,
}: {
  searchParams: Promise<{ job?: string }>;
}) {
  const { job } = await searchParams;
  redirect(job ? `/calendar?job=${encodeURIComponent(job)}` : "/calendar");
}
