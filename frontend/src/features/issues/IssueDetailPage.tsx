"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getCodexIssue } from "@/lib/api";
import type { CodexIssue } from "@/lib/types";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DagTab } from "./tabs/DagTab";
import { TasksRunsTab } from "./tabs/TasksRunsTab";
import { ArtifactsTab } from "./tabs/ArtifactsTab";
import { DiffMergeTab } from "./tabs/DiffMergeTab";

interface Props {
  issueId: string;
}

const TABS = ["dag", "tasks", "artifacts", "diff"] as const;
type TabId = (typeof TABS)[number];

function isTab(s: string | null): s is TabId {
  return s !== null && (TABS as readonly string[]).includes(s);
}

export function IssueDetailPage({ issueId }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const urlTab = params.get("tab");
  const initialTab: TabId = isTab(urlTab) ? urlTab : "dag";
  const [tab, setTab] = useState<TabId>(initialTab);
  const [issue, setIssue] = useState<CodexIssue | null>(null);

  useEffect(() => {
    getCodexIssue(issueId)
      .then(setIssue)
      .catch(() => setIssue(null));
  }, [issueId]);

  const onTabChange = (next: string) => {
    if (!isTab(next)) return;
    setTab(next);
    const sp = new URLSearchParams(params.toString());
    sp.set("tab", next);
    router.replace(`?${sp.toString()}`, { scroll: false });
  };

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-4 border-b border-border-subtle">
        <h1 className="text-xl font-black tracking-tight truncate">
          {issue?.title ?? "Issue"}
        </h1>
        <p className="text-xs text-text-muted mt-0.5">
          Phase: <b>{issue?.current_phase ?? "—"}</b> · Status: <b>{issue?.status ?? "—"}</b>
        </p>
      </div>
      <Tabs value={tab} onValueChange={onTabChange} className="flex-1 min-h-0 flex flex-col">
        <TabsList className="mx-6 mt-3 self-start">
          <TabsTrigger value="dag">DAG</TabsTrigger>
          <TabsTrigger value="tasks">Tasks · Runs</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
          <TabsTrigger value="diff">Diff · Merge</TabsTrigger>
        </TabsList>
        <div className="flex-1 min-h-0 overflow-auto">
          <TabsContent value="dag" className="m-0">
            <DagTab issueId={issueId} />
          </TabsContent>
          <TabsContent value="tasks" className="m-0">
            <TasksRunsTab issueId={issueId} issue={issue} />
          </TabsContent>
          <TabsContent value="artifacts" className="m-0">
            <ArtifactsTab issueId={issueId} />
          </TabsContent>
          <TabsContent value="diff" className="m-0">
            <DiffMergeTab issueId={issueId} issue={issue} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
