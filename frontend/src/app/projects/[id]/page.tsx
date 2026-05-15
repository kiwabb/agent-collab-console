import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { ProjectDashboard } from "@/features/projects/ProjectDashboard";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Project", href: "/projects" }, { label: id.slice(0, 8) }]}>
      <ProjectDashboard projectId={id} />
    </WorkbenchShell>
  );
}
