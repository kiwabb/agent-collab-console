import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { AuditLogPage } from "@/features/audit/AuditLogPage";

export default function Page() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Audit Log" }]}>
      <AuditLogPage />
    </WorkbenchShell>
  );
}
