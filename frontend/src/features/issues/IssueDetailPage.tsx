"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FolderArchive, GitPullRequest, Network } from "lucide-react";

import {
  getAgentMesh,
  getCodexIssue,
  getCodexIssueArtifacts,
  getCodexTasks,
  getSubAgentResults,
  pauseConductor,
  resumeConductor,
  steerCodexIssue,
  type AgentMessage,
  type SubAgentResultPayload,
} from "@/lib/api";
import type { Artifact, CodexIssue, CodexTask } from "@/lib/types";
import { useToast } from "@/components/ui/toast";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { StatusStrip } from "./components/StatusStrip";
import { LatestFailureAlert } from "./components/LatestFailureAlert";
import { DecisionTimeline } from "./components/DecisionTimeline";
import { SecondaryAccordion } from "./components/SecondaryAccordion";
import { ArtifactsPanel } from "./components/ArtifactsPanel";
import { IssueDiffPanel } from "./components/IssueDiffPanel";
import { MeshPanel } from "./components/MeshPanel";
import { DispatchDrawer } from "./components/DispatchDrawer";
import { CommandCenterChatBar } from "./components/CommandCenterChatBar";
import { WsConnectionBanner } from "./components/WsConnectionBanner";
import { SteerIssueDialog } from "./components/SteerIssueDialog";
import { useConductorPhase } from "./hooks/useConductorPhase";
import { useDecisionTimeline, type DecisionTimelineItem } from "./hooks/useDecisionTimeline";
import { useLatestFailure } from "./hooks/useLatestFailure";

interface Props {
  issueId: string;
}

export function IssueDetailPage({ issueId }: Props) {
  const { addToast } = useToast();
  const [issue, setIssue] = useState<CodexIssue | null>(null);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [subAgentResults, setSubAgentResults] = useState<SubAgentResultPayload[]>([]);
  const [agentMeshMessages, setAgentMeshMessages] = useState<AgentMessage[]>([]);
  const [drawerItem, setDrawerItem] = useState<DecisionTimelineItem | null>(null);
  const [steerOpen, setSteerOpen] = useState(false);
  const [steerDraft, setSteerDraft] = useState("");
  const [steerSending, setSteerSending] = useState(false);

  const phase = useConductorPhase(issueId);
  const { items: timeline, refresh: refreshTimeline } = useDecisionTimeline(issueId, tasks, subAgentResults);
  const latestFailure = useLatestFailure(tasks, timeline);

  const refreshCore = useCallback(async () => {
    const [nextIssue, nextTasks, nextArtifacts, nextResults, nextMesh] = await Promise.all([
      getCodexIssue(issueId).catch(() => null),
      getCodexTasks(null, issueId).catch(() => []),
      getCodexIssueArtifacts(issueId).catch(() => []),
      getSubAgentResults(issueId).catch(() => []),
      getAgentMesh(issueId).catch(() => []),
    ]);
    setIssue(nextIssue);
    setTasks(nextTasks);
    setArtifacts(nextArtifacts);
    setSubAgentResults(nextResults);
    setAgentMeshMessages(nextMesh);
  }, [issueId]);

  useEffect(() => {
    void refreshCore();
  }, [refreshCore]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn(
        "issue_updated",
        "issue_steered",
        "issue_abandoned",
        "issue_restored",
        "task_status",
        "task_created",
        "workflow_node_updated",
        "agent_message_posted",
      ),
    ),
    onEvent: () => { void refreshCore(); },
    throttleMs: 600,
  });

  const activeTask = useMemo(
    () => tasks.find((task) => ["running", "responding", "pending", "awaiting_review"].includes(String(task.status).toLowerCase())) ?? tasks[0] ?? null,
    [tasks],
  );
  const clarifyQuestion = useMemo(
    () => timeline.find((item) => item.kind === "clarification" && item.status !== "done")?.summary ?? null,
    [timeline],
  );
  const paused = phase.state?.conductor_status === "paused" || issue?.status === "awaiting_approval";

  const handlePause = async () => {
    try {
      await pauseConductor(issueId);
      await phase.refresh();
      addToast({ type: "success", title: "Conductor paused" });
    } catch (err) {
      addToast({ type: "error", title: "Pause failed", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleResume = async () => {
    try {
      await resumeConductor(issueId);
      await phase.refresh();
      addToast({ type: "success", title: "Conductor resumed" });
    } catch (err) {
      addToast({ type: "error", title: "Resume failed", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleSendSteer = async () => {
    const msg = steerDraft.trim();
    if (!msg) return;
    setSteerSending(true);
    try {
      await steerCodexIssue(issueId, msg);
      setSteerDraft("");
      setSteerOpen(false);
      await refreshCore();
      addToast({ type: "success", title: "Steer message sent" });
    } catch (err) {
      addToast({ type: "error", title: "Steer failed", message: err instanceof Error ? err.message : String(err) });
    } finally {
      setSteerSending(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_top_right,rgba(34,211,238,0.10),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.04),transparent_22%)]">
      <main className="mx-auto flex max-w-[1640px] flex-col gap-4 px-6 pb-28 pt-5">
        <WsConnectionBanner />
        <StatusStrip
          issue={issue}
          phase={phase}
          activeTask={activeTask}
          onPause={() => void handlePause()}
          onResume={() => void handleResume()}
          onSteer={() => setSteerOpen(true)}
        />
        <LatestFailureAlert
          failure={latestFailure}
          onJump={() => document.querySelector("[data-decision-timeline]")?.scrollIntoView({ behavior: "smooth", block: "start" })}
          onOpenDetail={() => {
            const item = timeline.find((candidate) => candidate.id === latestFailure?.id || candidate.taskId === latestFailure?.id) ?? null;
            setDrawerItem(item);
          }}
        />
        <DecisionTimeline items={timeline} onOpenItem={setDrawerItem} />
        <div className="grid gap-3">
          <SecondaryAccordion icon={<FolderArchive size={17} />} title="Artifacts" summary={`${artifacts.length} files produced`}>
            <ArtifactsPanel issueId={issueId} issue={issue} />
          </SecondaryAccordion>
          <SecondaryAccordion icon={<GitPullRequest size={17} />} title="Diff" summary="Worktree changes and merge controls">
            <IssueDiffPanel issueId={issueId} issue={issue} />
          </SecondaryAccordion>
          <SecondaryAccordion icon={<Network size={17} />} title="Mesh" summary={`${agentMeshMessages.length} agent messages`}>
            <MeshPanel issueId={issueId} />
          </SecondaryAccordion>
        </div>
      </main>
      <CommandCenterChatBar issueId={issueId} disabled={paused} clarifyQuestion={clarifyQuestion} onSent={() => void refreshTimeline()} />
      <DispatchDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
      <SteerIssueDialog
        open={steerOpen}
        draft={steerDraft}
        sending={steerSending}
        onOpenChange={setSteerOpen}
        onDraftChange={setSteerDraft}
        onSubmit={() => void handleSendSteer()}
      />
    </div>
  );
}
