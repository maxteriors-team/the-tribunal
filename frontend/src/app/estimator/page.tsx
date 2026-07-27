import { redirect } from "next/navigation";

// The Photo Designer now lives as a tab inside the unified Quotes & Estimates
// hub (one quoting home instead of competing estimator routes). This route is
// kept so existing deep links, bookmarks, and the command palette still land on
// the designer.
export default function EstimatorRoute() {
  redirect("/quotes?tab=designer");
}
