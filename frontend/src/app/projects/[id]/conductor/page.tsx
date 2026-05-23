import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { ProjectConductorRoutePage } from "@/features/projects/ProjectConductorRoutePage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <WorkbenchShell
      breadcrumbs={[
        { label: "Workspaces", href: `/projects/${id}` },
        { label: "Conductor", href: `/projects/${id}/conductor` },
      ]}
    >
      <ProjectConductorRoutePage projectId={id} />
    </WorkbenchShell>
  );
}
