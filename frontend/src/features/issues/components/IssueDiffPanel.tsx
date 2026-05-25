"use client";

import type { CodexIssue } from "@/lib/types";
import { DiffMergeTab } from "../tabs/DiffMergeTab";

export function IssueDiffPanel({ issueId, issue }: { issueId: string; issue: CodexIssue | null }) {
  return (
    <div className="h-[780px]">
      <DiffMergeTab issueId={issueId} issue={issue} active />
    </div>
  );
}
