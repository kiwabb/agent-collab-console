import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import WorkspaceConsole from "@/features/workspaces/WorkspaceConsole";

export default async function Page({ params }: { params: Promise<{ wsId: string }> }) {
  const { wsId } = await params;
  return (
    <WorkbenchShell workspaceId={wsId} breadcrumbs={[]}>
      <WorkspaceConsole workspaceId={wsId} />
    </WorkbenchShell>
  );
}
