import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { ArtifactsHubPage } from "@/features/artifacts/ArtifactsHubPage";

export default function Page() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Artifacts" }]}>
      <ArtifactsHubPage />
    </WorkbenchShell>
  );
}
