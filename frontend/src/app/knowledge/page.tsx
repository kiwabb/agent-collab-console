import { Suspense } from "react";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { KnowledgePage } from "@/features/knowledge/KnowledgePage";

export default function Page() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Knowledge" }]}>
      <Suspense fallback={<div className="p-6 text-sm text-text-muted">Loading…</div>}>
        <KnowledgePage />
      </Suspense>
    </WorkbenchShell>
  );
}
