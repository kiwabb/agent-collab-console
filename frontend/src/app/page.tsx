import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { InboxDashboard } from "@/features/inbox/InboxDashboard";

export default function Home() {
  return (
    <WorkbenchShell breadcrumbs={[{ label: "Inbox" }]}>
      <InboxDashboard />
    </WorkbenchShell>
  );
}
