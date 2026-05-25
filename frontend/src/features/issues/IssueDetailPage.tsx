"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FolderArchive, GitPullRequest, Network, Clock } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import {
  getAgentMesh,
  getCodexIssue,
  getCodexIssueArtifacts,
  getCodexTasks,
  getSubAgentResults,
  pauseConductor,
  resumeConductor,
  restartConductor,
  resetIssue,
  steerCodexIssue,
  type AgentMessage,
  type SubAgentResultPayload,
} from "@/lib/api";
import type { Artifact, CodexIssue, CodexTask } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
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
  const { t } = useI18n();
  const [issue, setIssue] = useState<CodexIssue | null>(null);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [subAgentResults, setSubAgentResults] = useState<SubAgentResultPayload[]>([]);
  const [agentMeshMessages, setAgentMeshMessages] = useState<AgentMessage[]>([]);
  const [drawerItem, setDrawerItem] = useState<DecisionTimelineItem | null>(null);
  const [steerOpen, setSteerOpen] = useState(false);
  const [steerDraft, setSteerDraft] = useState("");
  const [steerSending, setSteerSending] = useState(false);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [resetting, setResetting] = useState(false);

  const phase = useConductorPhase(issueId);
  const { items: timeline, refresh: refreshTimeline, liveThinking } = useDecisionTimeline(issueId, tasks, subAgentResults);
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
      addToast({ type: "success", title: t("issue.command.pauseToast") });
    } catch (err) {
      addToast({ type: "error", title: t("issue.command.pauseFailed"), message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleResume = async () => {
    try {
      await resumeConductor(issueId);
      await phase.refresh();
      addToast({ type: "success", title: t("issue.command.resumeToast") });
    } catch (err) {
      addToast({ type: "error", title: t("issue.command.resumeFailed"), message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleRestartOrSteer = async () => {
    const conductorStatus = phase.state?.conductor_status;
    const isAlive = conductorStatus === "running" || conductorStatus === "paused";
    if (isAlive) {
      setSteerOpen(true);
      return;
    }
    try {
      await restartConductor(issueId);
      await Promise.all([refreshCore(), phase.refresh()]);
      addToast({ type: "success", title: t("issue.command.restartToast") });
    } catch (err) {
      addToast({ type: "error", title: t("issue.command.restartFailed"), message: err instanceof Error ? err.message : String(err) });
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
      addToast({ type: "success", title: t("issue.command.steerSent") });
    } catch (err) {
      addToast({ type: "error", title: t("issue.command.steerFailed"), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setSteerSending(false);
    }
  };

  const handleResetConfirm = async () => {
    setResetting(true);
    try {
      await resetIssue(issueId);
      setResetConfirmOpen(false);
      await Promise.all([refreshCore(), phase.refresh()]);
      addToast({ type: "success", title: t("issue.command.resetToast") });
    } catch (err) {
      addToast({ type: "error", title: t("issue.command.resetFailed"), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="h-full flex flex-col overflow-hidden bg-[radial-gradient(circle_at_top_right,rgba(34,211,238,0.10),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.04),transparent_22%)]">
      {/* Scrollable Main Content */}
      <main className="flex-1 overflow-y-auto no-scrollbar mx-auto w-full max-w-[1640px] flex flex-col gap-4 px-6 pb-6 pt-5">
        <WsConnectionBanner />
        <StatusStrip
          issue={issue}
          phase={phase}
          activeTask={activeTask}
          onPause={() => void handlePause()}
          onResume={() => void handleResume()}
          onSteer={() => void handleRestartOrSteer()}
          onReset={() => setResetConfirmOpen(true)}
        />
        <LatestFailureAlert
          failure={latestFailure}
          onJump={() => document.querySelector("[data-decision-timeline]")?.scrollIntoView({ behavior: "smooth", block: "start" })}
          onOpenDetail={() => {
            const item = timeline.find((candidate) => candidate.id === latestFailure?.id || candidate.taskId === latestFailure?.id) ?? null;
            setDrawerItem(item);
          }}
        />
        <Tabs defaultValue="timeline" className="w-full flex-1 flex flex-col gap-4 min-h-0">
          <TabsList className="bg-surface/50 border border-border-subtle p-1 rounded-2xl w-full max-w-2xl mx-auto grid grid-cols-4 h-11 shrink-0">
            <TabsTrigger value="timeline" className="gap-2 text-[12px] font-bold py-2 rounded-xl transition-all cursor-pointer">
              <Clock size={14} />
              <span>{t("issue.command.timelineTitle")}</span>
            </TabsTrigger>
            <TabsTrigger value="artifacts" className="gap-2 text-[12px] font-bold py-2 rounded-xl transition-all cursor-pointer">
              <FolderArchive size={14} />
              <span>{t("issue.command.artifacts")}</span>
              <span className="ml-1 text-[10px] bg-brand-muted/30 text-brand px-1.5 py-0.5 rounded-full font-black font-mono">
                {artifacts.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="diff" className="gap-2 text-[12px] font-bold py-2 rounded-xl transition-all cursor-pointer">
              <GitPullRequest size={14} />
              <span>{t("issue.command.diff")}</span>
            </TabsTrigger>
            <TabsTrigger value="mesh" className="gap-2 text-[12px] font-bold py-2 rounded-xl transition-all cursor-pointer">
              <Network size={14} />
              <span>{t("issue.command.mesh")}</span>
              {agentMeshMessages.length > 0 && (
                <span className="ml-1 text-[10px] bg-brand-muted/30 text-brand px-1.5 py-0.5 rounded-full font-black font-mono">
                  {agentMeshMessages.length}
                </span>
              )}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="timeline" className="outline-none flex-1 min-h-0 flex flex-col">
            <DecisionTimeline items={timeline} onOpenItem={setDrawerItem} liveThinking={liveThinking} />
          </TabsContent>
          
          <TabsContent value="artifacts" className="outline-none flex-1 min-h-0 flex flex-col">
            <div className="enterprise-panel rounded-[24px] overflow-hidden bg-surface/88 p-1 flex-1 min-h-0 flex flex-col">
              <ArtifactsPanel issueId={issueId} issue={issue} />
            </div>
          </TabsContent>

          <TabsContent value="diff" className="outline-none flex-1 min-h-0 flex flex-col">
            <div className="enterprise-panel rounded-[24px] overflow-hidden bg-surface/88 p-1 flex-1 min-h-0 flex flex-col">
              <IssueDiffPanel issueId={issueId} issue={issue} />
            </div>
          </TabsContent>

          <TabsContent value="mesh" className="outline-none flex-1 min-h-0 flex flex-col">
            <div className="enterprise-panel rounded-[24px] overflow-hidden bg-surface/88 p-1 flex-1 min-h-0 flex flex-col">
              <MeshPanel issueId={issueId} />
            </div>
          </TabsContent>
        </Tabs>
      </main>

      {/* Permanently Docked Bottom Chat Bar */}
      <div className="shrink-0">
        <CommandCenterChatBar issueId={issueId} disabled={paused} clarifyQuestion={clarifyQuestion} onSent={() => void refreshTimeline()} />
      </div>

      <DispatchDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
      <SteerIssueDialog
        open={steerOpen}
        draft={steerDraft}
        sending={steerSending}
        onOpenChange={setSteerOpen}
        onDraftChange={setSteerDraft}
        onSubmit={() => void handleSendSteer()}
      />

      <Dialog open={resetConfirmOpen} onOpenChange={(open) => { if (!open) setResetConfirmOpen(false); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("issue.command.reset")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-text-secondary">{t("issue.command.resetConfirmBody")}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetConfirmOpen(false)} disabled={resetting}>
              {t("issue.cancel")}
            </Button>
            <Button variant="destructive" onClick={() => void handleResetConfirm()} disabled={resetting}>
              {resetting ? t("issue.command.resetting") : t("issue.command.resetConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
