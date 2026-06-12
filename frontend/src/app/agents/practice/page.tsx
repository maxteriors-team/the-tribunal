import { PracticeArena } from "@/components/agents/practice-arena";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default async function AgentsPracticePage({
  searchParams,
}: {
  searchParams: Promise<{ agentId?: string }>;
}) {
  const { agentId } = await searchParams;

  return (
    <AppSidebar>
      <PracticeArena initialAgentId={agentId ?? ""} />
    </AppSidebar>
  );
}
