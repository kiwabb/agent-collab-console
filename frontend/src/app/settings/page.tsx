import { SettingsPage } from "@/features/settings/SettingsPage";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";

export default function Page() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Settings" }]}>
      <SettingsPage />
    </WorkbenchShell>
  );
}
