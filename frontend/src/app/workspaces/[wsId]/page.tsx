import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { WorkspaceBoard } from "@/features/workspaces/WorkspaceBoard";

export default async function Page({ params }: { params: Promise<{ wsId: string }> }) {
  const { wsId } = await params;
  return (
    <WorkbenchShell workspaceId={wsId} breadcrumbs={[{ label: "Workspace" }]}>
      <WorkspaceBoard workspaceId={wsId} />
    </WorkbenchShell>
  );
}
