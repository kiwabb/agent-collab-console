import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { ApprovalsPage } from "@/features/approvals/ApprovalsPage";

export default function Page() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Approvals" }]}>
      <ApprovalsPage />
    </WorkbenchShell>
  );
}
