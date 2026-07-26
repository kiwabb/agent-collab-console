"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FolderArchive, GitPullRequest, Network, Clock, Workflow } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";

import {
  getAgentMesh,
  getSubAgentResults,
  pauseConductor,
  resumeConductor,
  restartConductor,
  resetIssue,
  type AgentMessage,
  type SubAgentResultPayload,
} from "@/lib/api/conductors";
import {
  getCodexIssue,
  getCodexIssueArtifacts,
  steerCodexIssue,
  getCodexIssueChecklist,
  type IssueChecklist,
} from "@/lib/api/issues";
import { getCodexTasks } from "@/lib/api/tasks";
import type { Artifact, CodexIssue, CodexTask } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { cn } from "@/lib/utils";
import { StatusStrip } from "./components/StatusStrip";
import { LatestFailureAlert } from "./components/LatestFailureAlert";
import { ConductorAlerts } from "./components/ConductorAlerts";
import { DecisionTimeline } from "./components/DecisionTimeline";
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
import { useConductorAlerts } from "./hooks/useConductorAlerts";
import { GitInfoCard } from "./components/GitInfoCard";
import { IssueSideStack } from "./components/IssueSideStack";
import { DagTab } from "./tabs/DagTab";

interface Props {
  issueId: string;
}

type IssueWorkbenchTab = "timeline" | "graph" | "artifacts" | "diff" | "mesh";

const ISSUE_WORKBENCH_TABS = new Set<IssueWorkbenchTab>([
  "timeline",
  "graph",
  "artifacts",
  "diff",
  "mesh",
]);

function readIssueWorkbenchTab(value: string | null): IssueWorkbenchTab {
  return value && ISSUE_WORKBENCH_TABS.has(value as IssueWorkbenchTab)
    ? (value as IssueWorkbenchTab)
    : "timeline";
}

export function IssueDetailPage({ issueId }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { addToast } = useToast();
  const { t } = useI18n();
  const [issue, setIssue] = useState<CodexIssue | null>(null);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [subAgentResults, setSubAgentResults] = useState<SubAgentResultPayload[]>([]);
  const [agentMeshMessages, setAgentMeshMessages] = useState<AgentMessage[]>([]);
  const [checklist, setChecklist] = useState<IssueChecklist | null>(null);
  // Track the open drawer by item id (not a snapshot): the live item is
  // re-derived from the latest `timeline` each render, so the drawer reflects
  // the running sub-agent's current execution-process id, status and result
  // as they stream in — a snapshot would freeze at click time (e.g. before
  // the EP id exists), leaving the live stream stuck on "waiting to start".
  const [drawerItemId, setDrawerItemId] = useState<string | null>(null);
  const [steerOpen, setSteerOpen] = useState(false);
  const [steerDraft, setSteerDraft] = useState("");
  const [steerSending, setSteerSending] = useState(false);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const activeTab = readIssueWorkbenchTab(searchParams.get("tab"));

  const phase = useConductorPhase(issueId);
  const {
    items: timeline,
    refresh: refreshTimeline,
    liveThinking,
  } = useDecisionTimeline(issueId, tasks, subAgentResults);
  const latestFailure = useLatestFailure(tasks, timeline);
  const { alerts: conductorAlerts, dismiss: dismissAlert } = useConductorAlerts(issueId);
  // Resolve the open drawer's item from the live timeline so it reflects the
  // running sub-agent's latest EP id / status / result. A timeline refresh can
  // momentarily not contain the item (e.g. turns refetch in flight); fall back
  // to the last known item so a transient miss doesn't unmount the drawer —
  // only an explicit close (drawerItemId === null) dismisses it.
  const lastDrawerItemRef = useRef<DecisionTimelineItem | null>(null);
  const drawerItem = useMemo<DecisionTimelineItem | null>(() => {
    if (!drawerItemId) {
      lastDrawerItemRef.current = null;
      return null;
    }
    const live = timeline.find((it) => it.id === drawerItemId) ?? null;
    if (live) lastDrawerItemRef.current = live;
    return lastDrawerItemRef.current;
  }, [timeline, drawerItemId]);

  const refreshCore = useCallback(async () => {
    const [nextIssue, nextTasks, nextArtifacts, nextResults, nextMesh, nextChecklist] =
      await Promise.all([
        getCodexIssue(issueId).catch(() => null),
        getCodexTasks(null, issueId).catch(() => []),
        getCodexIssueArtifacts(issueId).catch(() => []),
        getSubAgentResults(issueId).catch(() => []),
        getAgentMesh(issueId).catch(() => []),
        getCodexIssueChecklist(issueId).catch(() => null),
      ]);
    setIssue(nextIssue);
    setTasks(nextTasks);
    setArtifacts(nextArtifacts);
    setSubAgentResults(nextResults);
    setAgentMeshMessages(nextMesh);
    setChecklist(nextChecklist);
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
    onEvent: () => {
      void refreshCore();
    },
    throttleMs: 600,
  });

  const activeTask = useMemo(
    () =>
      tasks.find((task) =>
        ["running", "responding", "pending", "awaiting_review"].includes(
          String(task.status).toLowerCase(),
        ),
      ) ?? null,
    [tasks],
  );
  const clarifyQuestion = useMemo(
    () =>
      timeline.find((item) => item.kind === "clarification" && item.status !== "done")?.summary ??
      null,
    [timeline],
  );
  const paused =
    phase.state?.conductor_status === "paused" || issue?.status === "awaiting_approval";
  const isWorkbenchSchedulingMotion =
    !paused &&
    phase.state?.conductor_status !== "success" &&
    phase.phase !== "done" &&
    (phase.state?.conductor_status === "running" || Boolean(phase.phase));
  const workbenchMotionPhase =
    phase.phase === "awaiting_subagent" ? "dispatching" : (phase.phase ?? "thinking");

  const handlePause = async () => {
    try {
      await pauseConductor(issueId);
      await phase.refresh();
      addToast({ type: "success", title: t("issue.command.pauseToast") });
    } catch (err) {
      addToast({
        type: "error",
        title: t("issue.command.pauseFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const handleResume = async () => {
    try {
      await resumeConductor(issueId);
      await phase.refresh();
      addToast({ type: "success", title: t("issue.command.resumeToast") });
    } catch (err) {
      addToast({
        type: "error",
        title: t("issue.command.resumeFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
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
      addToast({
        type: "error",
        title: t("issue.command.restartFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
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
      addToast({
        type: "error",
        title: t("issue.command.steerFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
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
      addToast({
        type: "error",
        title: t("issue.command.resetFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setResetting(false);
    }
  };

  const handleTabChange = (value: string) => {
    const nextTab = readIssueWorkbenchTab(value);
    const params = new URLSearchParams(searchParams.toString());
    if (nextTab === "timeline") {
      params.delete("tab");
    } else {
      params.set("tab", nextTab);
    }
    const query = params.toString();
    router.replace(query ? `/issues/${issueId}?${query}` : `/issues/${issueId}`, { scroll: false });
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <main data-density="issue-workbench" className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1640px] px-3 pb-5 pt-3 lg:px-5">
          <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_minmax(320px,360px)] 2xl:items-start">
            <section className="min-w-0 space-y-3">
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

              <ConductorAlerts alerts={conductorAlerts} onDismiss={dismissAlert} />

              <LatestFailureAlert
                failure={latestFailure}
                onJump={() =>
                  document
                    .querySelector("[data-decision-timeline]")
                    ?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
                onOpenDetail={() => {
                  const item =
                    timeline.find(
                      (candidate) =>
                        candidate.id === latestFailure?.id ||
                        candidate.taskId === latestFailure?.id,
                    ) ?? null;
                  setDrawerItemId(item?.id ?? null);
                }}
              />

              <Tabs
                value={activeTab}
                onValueChange={handleTabChange}
                className="flex w-full flex-col gap-3"
              >
                <div
                  data-density={
                    isWorkbenchSchedulingMotion ? "workbench-scheduling-tabs" : "workbench-tabs"
                  }
                  className={cn(
                    "sticky top-0 z-20 border-b border-border-subtle/70 bg-background/95 pb-2 pt-1 backdrop-blur",
                    isWorkbenchSchedulingMotion &&
                      "motion-essential relative overflow-hidden border-brand/30",
                  )}
                >
                  {isWorkbenchSchedulingMotion && (
                    <span
                      aria-hidden
                      className="pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
                    />
                  )}
                  <TabsList className="grid h-10 w-full grid-cols-5 rounded-lg border border-border-subtle bg-surface/90 p-1 sm:max-w-[640px]">
                    <TabsTrigger
                      value="timeline"
                      data-density="workbench-scheduling-tab"
                      className={cn(
                        "min-w-0 gap-1.5 rounded-md px-1 text-[12px] font-bold transition-colors cursor-pointer",
                        isWorkbenchSchedulingMotion && "motion-essential text-brand",
                      )}
                    >
                      <Clock size={14} className="shrink-0" />
                      <span
                        aria-hidden
                        className="inline-flex size-3.5 shrink-0 items-center justify-center"
                      >
                        {isWorkbenchSchedulingMotion && (
                          <AgentThinkingIndicator phase={workbenchMotionPhase} size={12} />
                        )}
                      </span>
                      <span className="truncate max-sm:sr-only">
                        {t("issue.command.timelineTitle")}
                      </span>
                    </TabsTrigger>
                    <TabsTrigger
                      value="graph"
                      className="min-w-0 gap-1.5 rounded-md px-1 text-[12px] font-bold transition-colors cursor-pointer"
                    >
                      <Workflow size={14} className="shrink-0" />
                      <span className="truncate max-sm:sr-only">{t("issue.command.graph")}</span>
                    </TabsTrigger>
                    <TabsTrigger
                      value="mesh"
                      className="min-w-0 gap-1.5 rounded-md px-1 text-[12px] font-bold transition-colors cursor-pointer"
                    >
                      <Network size={14} className="shrink-0" />
                      <span className="truncate max-sm:sr-only">{t("issue.command.mesh")}</span>
                      {agentMeshMessages.length > 0 && (
                        <span className="font-mono text-[10px] font-black text-brand">
                          {agentMeshMessages.length}
                        </span>
                      )}
                    </TabsTrigger>
                    <TabsTrigger
                      value="artifacts"
                      className="min-w-0 gap-1.5 rounded-md px-1 text-[12px] font-bold transition-colors cursor-pointer"
                    >
                      <FolderArchive size={14} className="shrink-0" />
                      <span className="truncate max-sm:sr-only">
                        {t("issue.command.artifacts")}
                      </span>
                      <span className="font-mono text-[10px] font-black text-brand">
                        {artifacts.length}
                      </span>
                    </TabsTrigger>
                    <TabsTrigger
                      value="diff"
                      className="min-w-0 gap-1.5 rounded-md px-1 text-[12px] font-bold transition-colors cursor-pointer"
                    >
                      <GitPullRequest size={14} className="shrink-0" />
                      <span className="truncate max-sm:sr-only">{t("issue.command.diff")}</span>
                    </TabsTrigger>
                  </TabsList>
                </div>

                <TabsContent value="timeline" className="flex-none outline-none">
                  <DecisionTimeline
                    items={timeline}
                    onOpenItem={(it) => setDrawerItemId(it.id)}
                    liveThinking={liveThinking}
                  />
                </TabsContent>

                <TabsContent value="graph" className="flex-none outline-none">
                  <DagTab issueId={issueId} />
                </TabsContent>

                <TabsContent value="mesh" className="flex-none outline-none">
                  <div className="enterprise-panel min-h-[420px] rounded-lg bg-surface/90 p-1">
                    <MeshPanel issueId={issueId} />
                  </div>
                </TabsContent>

                <TabsContent value="artifacts" className="flex-none outline-none">
                  <div className="enterprise-panel min-h-[420px] rounded-lg bg-surface/90 p-1">
                    <ArtifactsPanel issueId={issueId} issue={issue} />
                  </div>
                </TabsContent>

                <TabsContent value="diff" className="flex-none outline-none">
                  <div className="enterprise-panel min-h-[420px] rounded-lg bg-surface/90 p-1">
                    <IssueDiffPanel issueId={issueId} issue={issue} />
                  </div>
                </TabsContent>
              </Tabs>
            </section>

            <aside className="min-w-0 space-y-3 2xl:sticky 2xl:top-3">
              {issue && <GitInfoCard issue={issue} onIssueUpdated={setIssue} />}
              <IssueSideStack
                issueId={issueId}
                checklist={checklist}
                issue={issue}
                onIssueUpdated={setIssue}
              />
            </aside>
          </div>
        </div>
      </main>

      <div className="shrink-0 pb-[env(safe-area-inset-bottom)] bg-background">
        <CommandCenterChatBar
          issueId={issueId}
          disabled={paused}
          clarifyQuestion={clarifyQuestion}
          onSent={() => void refreshTimeline()}
        />
      </div>

      <DispatchDrawer item={drawerItem} onClose={() => setDrawerItemId(null)} />
      <SteerIssueDialog
        open={steerOpen}
        draft={steerDraft}
        sending={steerSending}
        onOpenChange={setSteerOpen}
        onDraftChange={setSteerDraft}
        onSubmit={() => void handleSendSteer()}
      />

      <Dialog
        open={resetConfirmOpen}
        onOpenChange={(open) => {
          if (!open) setResetConfirmOpen(false);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("issue.command.reset")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-text-secondary">{t("issue.command.resetConfirmBody")}</p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setResetConfirmOpen(false)}
              disabled={resetting}
            >
              {t("issue.cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleResetConfirm()}
              disabled={resetting}
            >
              {resetting ? t("issue.command.resetting") : t("issue.command.resetConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
