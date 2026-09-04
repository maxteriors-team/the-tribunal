import type { Metadata } from "next";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { TechnicianScoreboardPage } from "@/components/scoreboard/technician-scoreboard-page";

export const metadata: Metadata = { title: "Lighting League" };

export default function ScoreboardPage() {
  return (
    <AppSidebar>
      <TechnicianScoreboardPage />
    </AppSidebar>
  );
}
