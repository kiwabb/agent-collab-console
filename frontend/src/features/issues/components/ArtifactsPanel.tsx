"use client";

import type { CodexIssue } from "@/lib/types";
import { ArtifactsTab } from "../tabs/ArtifactsTab";

export function ArtifactsPanel({ issueId, issue }: { issueId: string; issue: CodexIssue | null }) {
  return (
    <div className="h-full min-h-0">
      <ArtifactsTab issueId={issueId} issue={issue} active />
    </div>
  );
}
