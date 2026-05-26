"use client";

import type { CodexIssue } from "@/lib/types";
import { DiffMergeTab } from "../tabs/DiffMergeTab";

export function IssueDiffPanel({ issueId, issue }: { issueId: string; issue: CodexIssue | null }) {
  return (
    <div className="h-full min-h-0">
      <DiffMergeTab issueId={issueId} issue={issue} active />
    </div>
  );
}
