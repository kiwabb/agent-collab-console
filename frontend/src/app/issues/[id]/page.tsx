"use client";

import { useEffect, useState } from "react";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { IssueDetailPage } from "@/features/issues/IssueDetailPage";
import { getCodexIssue } from "@/lib/api";

import { Loader } from "@/components/ui/loader";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const [id, setId] = useState<string | null>(null);
  // Resolve the issue's owning workspace so WorkbenchShell can open the
  // per-workspace WebSocket. Without this, ExecutionProcessesProvider gets
  // workspaceId=null and lastEvent never arrives — every child component on
  // this page falls back to polling.
  const [workspaceId, setWorkspaceId] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    void params.then((p) => {
      if (!cancelled) setId(p.id);
    });
    return () => {
      cancelled = true;
    };
  }, [params]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getCodexIssue(id)
      .then((issue) => {
        if (!cancelled) setWorkspaceId(issue.session_id ?? null);
      })
      .catch(() => {
        if (!cancelled) setWorkspaceId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (!id) {
    return (
      <WorkbenchShell breadcrumbs={[{ label: "Issue" }]}>
        <Loader variant="full" label="Loading Issue Details..." />
      </WorkbenchShell>
    );
  }


  return (
    <WorkbenchShell
      breadcrumbs={[{ label: "Issue" }, { label: id.slice(0, 8) }]}
      workspaceId={workspaceId ?? null}
      issueId={id}
    >
      <IssueDetailPage issueId={id} />
    </WorkbenchShell>
  );
}
