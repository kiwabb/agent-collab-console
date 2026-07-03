import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { ResumePage } from "@/features/resume/ResumePage";

export default function Page() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Resume" }]}>
      <ResumePage />
    </WorkbenchShell>
  );
}
