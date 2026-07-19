import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { ProjectEnvConfigRoutePage } from "@/features/projects/ProjectEnvConfigRoutePage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <WorkbenchShell
      projectId={id}
      breadcrumbs={[
        { label: "Workspaces", href: `/projects/${id}` },
        { label: "Environment", href: `/projects/${id}/env` },
      ]}
    >
      <ProjectEnvConfigRoutePage projectId={id} />
    </WorkbenchShell>
  );
}
