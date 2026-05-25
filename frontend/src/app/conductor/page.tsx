import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { ConductorMonitorPage } from "@/features/conductors/ConductorMonitorPage";

export default function Page() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Conductor Monitor" }]}>
      <ConductorMonitorPage />
    </WorkbenchShell>
  );
}
