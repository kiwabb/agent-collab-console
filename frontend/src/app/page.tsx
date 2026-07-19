import { redirect } from "next/navigation";

import { InboxDashboard } from "@/features/inbox/InboxDashboard";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";

interface Props {
  searchParams: Promise<{ project?: string | string[] | undefined }>;
}

export default async function Home({ searchParams }: Props) {
  const params = await searchParams;
  const project = typeof params.project === "string" ? params.project.trim() : "";
  if (project) {
    redirect(`/projects/${encodeURIComponent(project)}`);
  }

  return (
    <WorkbenchShell breadcrumbs={[{ label: "Inbox" }]}>
      <InboxDashboard />
    </WorkbenchShell>
  );
}
