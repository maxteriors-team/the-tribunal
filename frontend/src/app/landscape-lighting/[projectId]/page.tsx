import { LightingProjectEditor } from "@/components/landscape-lighting/lighting-project-editor";
import { AppSidebar } from "@/components/layout/app-sidebar";

interface LandscapeLightingProjectPageProps {
  params: Promise<{ projectId: string }>;
}

export default async function LandscapeLightingProjectPage({
  params,
}: LandscapeLightingProjectPageProps) {
  const { projectId } = await params;
  return (
    <AppSidebar>
      <LightingProjectEditor projectId={projectId} />
    </AppSidebar>
  );
}
