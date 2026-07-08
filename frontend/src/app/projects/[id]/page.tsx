import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { ProjectWorkspacesPage } from "@/features/projects/ProjectWorkspacesPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Workspaces", href: `/projects/${id}` }]}>
      <ProjectWorkspacesPage projectId={id} />
    </WorkbenchShell>
  );
}
