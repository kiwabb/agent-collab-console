import { Suspense } from "react";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { KnowledgePage } from "@/features/knowledge/KnowledgePage";
import { Loader } from "@/components/ui/loader";

export default function Page() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Knowledge" }]}>
      <Suspense fallback={<Loader variant="full" label="Loading Knowledge..." />}>
        <KnowledgePage />
      </Suspense>
    </WorkbenchShell>
  );
}
