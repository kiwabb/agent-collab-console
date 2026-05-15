import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { IssueDetailPage } from "@/features/issues/IssueDetailPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Issue" }, { label: id.slice(0, 8) }]}>
      <IssueDetailPage issueId={id} />
    </WorkbenchShell>
  );
}
