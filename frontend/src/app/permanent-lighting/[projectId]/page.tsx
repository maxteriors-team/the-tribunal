import { LightingProjectEditor } from "@/components/landscape-lighting/lighting-project-editor";
import { AppSidebar } from "@/components/layout/app-sidebar";

interface PermanentLightingProjectPageProps {
  params: Promise<{ projectId: string }>;
}

export default async function PermanentLightingProjectPage({
  params,
}: PermanentLightingProjectPageProps) {
  const { projectId } = await params;
  return (
    <AppSidebar>
      <LightingProjectEditor projectId={projectId} />
    </AppSidebar>
  );
}
