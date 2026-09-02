import { AppSidebar } from "@/components/layout/app-sidebar";
import { OpportunityWorkspace } from "@/components/opportunities/opportunity-workspace";

interface OpportunityPageProps {
  params: Promise<{ id: string }>;
}

export default async function OpportunityPage({ params }: OpportunityPageProps) {
  const { id } = await params;

  return (
    <AppSidebar>
      <OpportunityWorkspace opportunityId={id} />
    </AppSidebar>
  );
}
