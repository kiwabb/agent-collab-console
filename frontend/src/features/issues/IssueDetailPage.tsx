"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { GitBranch, GitFork, MessageSquarePlus, Loader2 } from "lucide-react";
import { useI18n } from "@/providers/I18nProvider";
import {
  forkCodexIssue,
  approveCodexIssuePlan,
  getCodexIssue,
  getCodexIssueChecklist,
  qaReviewCodexIssue,
  steerCodexIssue,
  getSubAgentResults,
  getAgentMesh,
  getConductorState,
  type IssueChecklist,
  type SubAgentResultPayload,
  type AgentMessage,
  type ConductorStatePayload,
} from "@/lib/api";
import type { CodexIssue } from "@/lib/types";
import { SubAgentResultCard } from "./components/SubAgentResultCard";
import { AgentMeshGraph } from "./components/AgentMeshGraph";
import { ConductorChatBar } from "./components/ConductorChatBar";
import { cn } from "@/lib/utils";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { DagTab } from "./tabs/DagTab";
import { TasksRunsTab } from "./tabs/TasksRunsTab";
import { ArtifactsTab } from "./tabs/ArtifactsTab";
import { DiffMergeTab } from "./tabs/DiffMergeTab";
import { CollabFeedTab } from "./tabs/CollabFeedTab";
import { IssuePipelineTrace } from "./components/IssuePipelineTrace";
import { IssueSideStack } from "./components/IssueSideStack";
import { IssueActivityTimelineHorizontal } from "./components/IssueActivityTimelineHorizontal";
import { FloatingIssueChip } from "./components/FloatingIssueChip";
import { LiveThinkingDock } from "./components/LiveThinkingDock";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

interface Props {
  issueId: string;
}

const TABS = ["agent", "dag", "tasks", "artifacts", "diff", "collab"] as const;
type TabId = (typeof TABS)[number];

function isTab(s: string | null): s is TabId {
  return s !== null && (TABS as readonly string[]).includes(s);
}

const STATUS_LABEL: Record<string, string> = {
  open: "Queued",
  in_progress: "Running",
  completed: "Done",
  failed: "Failed",
  awaiting_approval: "Awaiting approval",
  awaiting_review: "Awaiting review",
  awaiting_merge: "Awaiting merge",
  cancelled: "Cancelled",
};

export function IssueDetailPage({ issueId }: Props) {
  const { t } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const { addToast } = useToast();
  const urlTab = params.get("tab");
  const initialTab: TabId = isTab(urlTab) ? urlTab : "dag";
  const [tab, setTab] = useState<TabId>(initialTab);
  const [issue, setIssue] = useState<CodexIssue | null>(null);
  const [checklist, setChecklist] = useState<IssueChecklist | null>(null);
  const [steerOpen, setSteerOpen] = useState(false);
  const [steerDraft, setSteerDraft] = useState("");
  const [steerSending, setSteerSending] = useState(false);
  const [forking, setForking] = useState(false);
  const [planDraft, setPlanDraft] = useState("");
  const [approvingPlan, setApprovingPlan] = useState(false);
  const [qaRejectDraft, setQaRejectDraft] = useState("");
  const [qaReviewBusy, setQaReviewBusy] = useState<"approve" | "reject" | null>(null);
  const [conductorDecision, setConductorDecision] = useState<{
    action: string;
    reason?: string;
    note?: string | null;
    role?: string;
    receivedAt: number;
  } | null>(null);
  const [subAgentResults, setSubAgentResults] = useState<SubAgentResultPayload[]>([]);
  const [agentMeshMessages, setAgentMeshMessages] = useState<AgentMessage[]>([]);
  const [conductorState, setConductorState] = useState<ConductorStatePayload | null>(null);

  const handleFork = useCallback(async () => {
    setForking(true);
    try {
      const forked = await forkCodexIssue(issueId);
      addToast({
        type: "success",
        title: t("issue.forked"),
        message: t("issue.forkHint"),
      });
      router.push(`/issues/${forked.id}`);
    } catch (err) {
      addToast({
        type: "error",
        title: t("issue.forkFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setForking(false);
    }
  }, [issueId, addToast, router]);

  const handleSendSteer = useCallback(async () => {
    const msg = steerDraft.trim();
    if (!msg) return;
    setSteerSending(true);
    try {
      await steerCodexIssue(issueId, msg);
      addToast({
        type: "success",
        title: t("issue.steerSent"),
        message: t("issue.steerSentHint"),
      });
      setSteerDraft("");
      setSteerOpen(false);
    } catch (err) {
      addToast({
        type: "error",
        title: t("issue.steerFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSteerSending(false);
    }
  }, [issueId, steerDraft, addToast]);

  const loadIssue = useCallback(async () => {
    try {
      const next = await getCodexIssue(issueId);
      setIssue(next);
    } catch {
      setIssue(null);
    }
  }, [issueId]);

  useEffect(() => {
    setConductorDecision(null);
    void loadIssue();
  }, [loadIssue]);

  // Event-driven refresh: react to backend mutations on this issue. The
  // workspace-scoped WS (set up by /issues/[id]/page.tsx via WorkbenchShell)
  // delivers issue_updated/task_status/workflow_node_updated/issue_steered.
  // Polling below remains as a 15s fallback for the case where the WS dropped
  // or the page is opened without a workspace context.
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn(
        "issue_updated",
        "issue_steered",
        "issue_restored",
        "task_status",
        "workflow_node_updated",
      ),
    ),
    onEvent: () => { void loadIssue(); },
    throttleMs: 300,
  });

  // Slow fallback poll for cases where events don't reach us (no WS scope,
  // closed tab, dropped connection). Stops once the issue lands terminal.
  useEffect(() => {
    const terminal = new Set(["completed", "failed", "cancelled", "abandoned"]);
    if (terminal.has(issue?.status ?? "")) return;
    const id = window.setInterval(() => { void loadIssue(); }, 15000);
    return () => window.clearInterval(id);
  }, [issue?.status, loadIssue]);

  // A3: refresh acceptance checklist when this issue or any of its tasks
  // change state. The interval here is just a safety net (30s) — most
  // updates flow through the bus event above.
  const refreshChecklist = useCallback(async () => {
    try {
      const c = await getCodexIssueChecklist(issueId);
      setChecklist(c);
    } catch {
      // silent — endpoint absent → no checklist
    }
  }, [issueId]);

  useEffect(() => {
    void refreshChecklist();
    const id = window.setInterval(() => { void refreshChecklist(); }, 30000);
    return () => window.clearInterval(id);
  }, [refreshChecklist]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("task_status", "workflow_node_updated", "issue_updated"),
    ),
    onEvent: () => { void refreshChecklist(); },
    throttleMs: 500,
  });

  // Conductor observes every task completion. Capture the latest decision so
  // the user gets visible feedback that the workflow's "5th agent" is alive.
  // For non-proceed actions we also pop a toast.
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_decision"),
    ),
    onEvent: (evt) => {
      const e = evt as { action?: string; reason?: string; note?: string | null; role?: string };
      const action = e.action ?? "proceed";
      setConductorDecision({
        action,
        reason: e.reason,
        note: e.note ?? null,
        role: e.role,
        receivedAt: Date.now(),
      });
      if (action === "note") {
        addToast({ type: "info", title: t("conductor.toastNote"), message: e.note ?? "" });
      } else if (action === "escalate") {
        addToast({ type: "warning", title: t("conductor.toastEscalate"), message: e.reason ?? "" });
      }
    },
  });

  useEffect(() => {
    if (isTab(urlTab) && urlTab !== tab) setTab(urlTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlTab]);

  useEffect(() => {
    if (issue?.status === "awaiting_approval") {
      setPlanDraft(issue.review_comment ?? "");
      return;
    }
    setPlanDraft("");
  }, [issue?.status, issue?.review_comment]);

  const loadAgentTab = useCallback(async () => {
    try {
      const [results, mesh, cState] = await Promise.all([
        getSubAgentResults(issueId).catch(() => [] as SubAgentResultPayload[]),
        getAgentMesh(issueId).catch(() => [] as AgentMessage[]),
        getConductorState(issueId).catch(() => null),
      ]);
      setSubAgentResults(results);
      setAgentMeshMessages(mesh);
      setConductorState(cState);
    } catch {
      // silent
    }
  }, [issueId]);

  useEffect(() => {
    if (tab === "agent") void loadAgentTab();
  }, [tab, issueId, loadAgentTab]);

  const onTabChange = (next: string) => {
    if (!isTab(next)) return;
    setTab(next);
    const sp = new URLSearchParams(params.toString());
    sp.set("tab", next);
    router.replace(`?${sp.toString()}`, { scroll: false });
  };

  const handleApprovePlan = useCallback(async () => {
    const draft = planDraft.trim();
    if (!draft && !(issue?.review_comment || "").trim()) return;
    setApprovingPlan(true);
    try {
      await approveCodexIssuePlan(issueId, draft);
      addToast({
        type: "success",
        title: t("issue.planApproval.approved"),
      });
      await loadIssue();
    } catch (err) {
      addToast({
        type: "error",
        title: t("issue.planApproval.failed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setApprovingPlan(false);
    }
  }, [planDraft, issue?.review_comment, issueId, addToast, loadIssue, t]);

  const handleQaReview = useCallback(
    async (decision: "approve" | "reject") => {
      setQaReviewBusy(decision);
      try {
        await qaReviewCodexIssue(issueId, decision, decision === "reject" ? qaRejectDraft.trim() || null : null);
        addToast({
          type: "success",
          title: decision === "approve" ? t("issue.qaReview.approved") : t("issue.qaReview.rejected"),
        });
        if (decision === "reject") setQaRejectDraft("");
        await loadIssue();
      } catch (err) {
        addToast({
          type: "error",
          title: t("issue.qaReview.failed"),
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setQaReviewBusy(null);
      }
    },
    [issueId, qaRejectDraft, addToast, loadIssue, t],
  );

  // Bug-fix: when the orchestration has marched the issue's `current_phase`
  // all the way to `done` but the bookkeeping `status` field hasn't been
  // flipped from the default `open`, the header used to claim "Queued" which
  // is misleading. Derive a smarter label from the phase in that case.
  const effectiveStatus =
    issue?.status === "open" && (issue.current_phase === "done" || issue.current_phase === "completed")
      ? "completed"
      : issue?.status;
  const kind = inferStatusKind(effectiveStatus);
  const statusLabel = effectiveStatus
    ? STATUS_LABEL[effectiveStatus] ?? effectiveStatus
    : "—";

  return (
    // Single scroll container so Hero + Pipeline trace scroll together
    // with the tabs/side-stack body instead of sticking at the top.
    <div className="h-full overflow-y-auto">
      {/* === HERO === */}
      <section className="px-8 pt-6 pb-4 max-w-[1640px] w-full mx-auto">
        <div className="flex items-end justify-between gap-6">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-text-muted mb-2">
              <StatusBadge kind={kind} label={statusLabel} />
              <span className="text-text-faint">·</span>
              <span>
                {t("issue.metaLabel")}{" "}
                <b className="text-text-secondary font-medium">
                  {issueId.slice(0, 8)}
                </b>
              </span>
              <span className="text-text-faint">·</span>
              <span className="uppercase tracking-wider">CODEX 智能体</span>
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight leading-[1.15] text-foreground max-w-[760px] text-balance">
              {renderTitleWithMono(issue?.title ?? t("issue.titleFallback"))}
            </h1>
            <div className="flex items-center gap-3.5 mt-2.5 text-[12.5px] text-text-secondary flex-wrap">
              {issue?.git_branch && (
                <span className="inline-flex items-center gap-1.5 bg-surface-raised border border-border-subtle px-2.5 py-1 rounded-md font-mono text-[12px] text-foreground">
                  <GitBranch size={13} className="text-text-muted" />
                  {issue.git_branch}
                </span>
              )}
              {issue?.created_at && (
                <span className="inline-flex items-center gap-1.5">
                  <span className="text-text-muted">创建</span>
                  <b className="font-mono font-medium text-foreground">
                    {new Date(issue.created_at).toLocaleTimeString("zh-CN", {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </b>
                </span>
              )}
              <HeroDurationBit
                issueId={issueId}
                reloadKey={issue?.updated_at ?? undefined}
              />
              <span className="inline-flex items-center gap-1.5">
                <span className="text-text-muted">阶段</span>
                <b className="font-mono font-medium uppercase text-brand-strong">
                  {issue?.current_phase ?? "—"}
                </b>
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2.5 shrink-0">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleFork()}
              disabled={forking || !issue?.git_worktree_path}
              title={t("issue.forkHelp")}
              className="gap-2 h-[34px] px-3.5 text-[13px] font-medium rounded-lg"
            >
              {forking ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <GitFork size={14} />
              )}
              {t("issue.fork")}
            </Button>
            <Button
              size="sm"
              onClick={() => setSteerOpen(true)}
              disabled={!issue?.git_worktree_path}
              title={
                issue?.git_worktree_path
                  ? t("issue.steerHelp")
                  : t("issue.noActiveWorktree")
              }
              className="gap-2 h-[34px] px-3.5 text-[13px] font-semibold bg-brand hover:bg-brand-strong text-black rounded-lg shadow-[0_4px_14px_-4px_var(--color-brand-ring)]"
            >
              <MessageSquarePlus size={14} />
              {t("issue.steer")}
            </Button>
          </div>
        </div>

        {/* Pipeline trace immediately under hero */}
        <div className="mt-5">
          <IssuePipelineTrace
            issueId={issueId}
            reloadKey={issue?.updated_at ?? undefined}
          />
        </div>
      </section>

        {/* Conductor banner — only when there's a recent (< 60s) non-proceed
            decision. We avoid showing "proceed" to keep it from being noise. */}
        {conductorDecision && Date.now() - conductorDecision.receivedAt < 60000 && conductorDecision.action !== "proceed" && (
          <div className={cn(
            "mx-8 mt-3 rounded-lg border px-3 py-2 text-[12px] flex items-start gap-2",
            conductorDecision.action === "escalate"
              ? "border-warning/40 bg-warning/10 text-warning"
              : "border-info/30 bg-info/[0.06] text-foreground",
          )}>
            <span aria-hidden className="font-mono text-base leading-none">🎙️</span>
            <div className="flex-1 min-w-0">
              <div className="font-semibold">
                {conductorDecision.action === "escalate" ? t("conductor.bannerEscalate") : t("conductor.bannerNote")}
              </div>
              <div className="text-text-muted">
                {conductorDecision.note || conductorDecision.reason}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setConductorDecision(null)}
              aria-label="dismiss"
              className="shrink-0 text-text-muted hover:text-foreground"
            >
              ✕
            </button>
          </div>
        )}

        {issue?.status === "awaiting_review" && (
          <div className="mt-4 mx-8 rounded-xl border border-success/40 bg-success/[0.04] p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-success">
                  {t("issue.qaReview.title")}
                </h2>
                <p className="text-[12px] text-text-muted mt-0.5">
                  {t("issue.qaReview.description")}
                </p>
              </div>
              <StatusBadge kind="awaiting" label={t("issue.status.awaitingReview")} />
            </div>
            <textarea
              value={qaRejectDraft}
              onChange={(e) => setQaRejectDraft(e.target.value)}
              rows={4}
              placeholder={t("issue.qaReview.rejectPlaceholder")}
              className="mt-3 w-full rounded-md border border-border-subtle bg-background px-3 py-2 text-[13px] font-mono outline-none focus:ring-2 focus:ring-success/40"
            />
            <div className="mt-3 flex items-center justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleQaReview("reject")}
                disabled={qaReviewBusy !== null}
                className="gap-1.5"
              >
                {qaReviewBusy === "reject" ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" />
                    {t("issue.qaReview.rejectBusy")}
                  </span>
                ) : (
                  t("issue.qaReview.reject")
                )}
              </Button>
              <Button
                size="sm"
                onClick={() => void handleQaReview("approve")}
                disabled={qaReviewBusy !== null}
                className="gap-1.5 bg-success text-black hover:bg-success/90 font-semibold"
              >
                {qaReviewBusy === "approve" ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" />
                    {t("issue.qaReview.approveBusy")}
                  </span>
                ) : (
                  t("issue.qaReview.approve")
                )}
              </Button>
            </div>
          </div>
        )}

        {issue?.status === "awaiting_approval" && (
          <div className="mt-4 max-w-3xl rounded-xl border border-brand/40 bg-brand/[0.04] p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-brand">
                  {t("issue.planApproval.title")}
                </h2>
                <p className="text-[12px] text-text-muted mt-0.5">
                  {t("issue.planApproval.description")}
                </p>
              </div>
              <StatusBadge kind="awaiting" label={t("workspace.console.status.awaitingApproval")} />
            </div>
            <textarea
              value={planDraft}
              onChange={(e) => setPlanDraft(e.target.value)}
              rows={7}
              placeholder={t("issue.planApproval.placeholder")}
              className="mt-3 w-full rounded-md border border-border-subtle bg-background px-3 py-2 text-[13px] font-mono outline-none focus:ring-2 focus:ring-brand/50"
            />
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-[12px] text-text-muted">
                {t("issue.planApproval.helper")}
              </p>
              <Button
                size="sm"
                onClick={() => void handleApprovePlan()}
                disabled={approvingPlan || (!planDraft.trim() && !(issue.review_comment || "").trim())}
                className="gap-1.5 bg-brand hover:bg-brand-strong text-black font-semibold"
              >
                {approvingPlan ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" />
                    {t("issue.planApproval.saving")}
                  </span>
                ) : (
                  t("issue.planApproval.approve")
                )}
              </Button>
            </div>
          </div>
        )}
      <Dialog open={steerOpen} onOpenChange={setSteerOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("issue.steerDialogTitle")}</DialogTitle>
            <DialogDescription>
              {t("issue.steerDialogBody")}
            </DialogDescription>
          </DialogHeader>
          <textarea
            autoFocus
            value={steerDraft}
            onChange={(e) => setSteerDraft(e.target.value)}
            rows={5}
            placeholder={t("issue.steerPlaceholder")}
            className="w-full rounded-md border border-border-subtle bg-background px-3 py-2 text-[13px] font-mono focus:outline-none focus:ring-2 focus:ring-brand/50"
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setSteerOpen(false)}
              disabled={steerSending}
            >
              {t("issue.cancel")}
            </Button>
            <Button
              onClick={() => void handleSendSteer()}
              disabled={steerSending || !steerDraft.trim()}
              className="bg-brand hover:bg-brand-strong text-black font-semibold"
            >
              {steerSending ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin" /> {t("issue.sending")}
                </span>
              ) : (
                t("issue.sendToAgent")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* === BODY GRID: tabs panel + right-side stack === */}
      <div className="px-8 pb-16">
        <div className="max-w-[1640px] w-full mx-auto grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px] gap-5 items-start">
          {/* LEFT panel — tabs. Explicit min-height keeps ReactFlow / Gantt /
              Diff split views from collapsing to 0 inside the body grid. */}
          <div className="min-w-0 min-h-[640px] rounded-2xl border border-border-subtle bg-surface overflow-hidden flex flex-col">
            <Tabs
              value={tab}
              onValueChange={onTabChange}
              className="flex flex-col flex-1 min-h-0"
            >
              <TabsList
                variant="line"
                className="px-2 pt-2 self-stretch border-b border-border-subtle gap-0.5 shrink-0"
              >
                <UnderlineTab value="agent" label="Agent" />
                <UnderlineTab value="dag" label="DAG" />
                <UnderlineTab value="tasks" label={t("issue.tab.tasksRuns")} />
                <UnderlineTab value="artifacts" label={t("console.artifacts")} />
                <UnderlineTab value="diff" label={t("issue.tab.diffMerge")} />
                <UnderlineTab value="collab" label={t("issue.tab.collab")} />
              </TabsList>
              <div className="flex flex-col flex-1 min-h-0">
                <TabsContent
                  value="agent"
                  className="m-0 flex flex-col min-h-0 flex-1 overflow-hidden"
                >
                  <AgentTabContent
                    issueId={issueId}
                    projectId={issue?.project_id ?? null}
                    conductorState={conductorState}
                    subAgentResults={subAgentResults}
                    agentMeshMessages={agentMeshMessages}
                    onConductorSent={() => void loadAgentTab()}
                  />
                </TabsContent>
                <TabsContent
                  value="dag"
                  className="m-0 h-full flex flex-col min-h-0 flex-1"
                >
                  <DagTab issueId={issueId} />
                </TabsContent>
                <TabsContent
                  value="tasks"
                  className="m-0 h-full flex flex-col min-h-0 flex-1"
                >
                  <TasksRunsTab issueId={issueId} issue={issue} />
                </TabsContent>
                <TabsContent
                  value="artifacts"
                  className="m-0 h-full flex flex-col min-h-0 flex-1"
                >
                  <ArtifactsTab
                    issueId={issueId}
                    active={tab === "artifacts"}
                    issue={issue}
                  />
                </TabsContent>
                <TabsContent
                  value="diff"
                  className="m-0 h-full flex flex-col min-h-0 flex-1 overflow-y-auto"
                >
                  <DiffMergeTab
                    issueId={issueId}
                    issue={issue}
                    active={tab === "diff"}
                  />
                </TabsContent>
                <TabsContent
                  value="collab"
                  className="m-0 h-full flex flex-col min-h-0 flex-1"
                >
                  <CollabFeedTab issueId={issueId} active={tab === "collab"} />
                </TabsContent>
              </div>
            </Tabs>
          </div>

          {/* RIGHT side stack */}
          <IssueSideStack
            issueId={issueId}
            checklist={checklist}
            reloadKey={issue?.updated_at ?? undefined}
          />
        </div>
        {/* Horizontal activity timeline spanning the full width below
            the tabs/sidebar grid. Replaces the in-sidebar ActivityCard. */}
        <div className="max-w-[1640px] w-full mx-auto">
          <IssueActivityTimelineHorizontal
            issueId={issueId}
            reloadKey={issue?.updated_at ?? undefined}
          />
        </div>
      </div>
      <FloatingIssueChip badge={issueId.slice(0, 1)} />
      <LiveThinkingDock issueId={issueId} />
    </div>
  );
}

interface AgentTabContentProps {
  issueId: string;
  projectId: string | null;
  conductorState: ConductorStatePayload | null;
  subAgentResults: SubAgentResultPayload[];
  agentMeshMessages: AgentMessage[];
  onConductorSent?: () => void;
}

function AgentTabContent({
  projectId,
  conductorState,
  subAgentResults,
  agentMeshMessages,
  onConductorSent,
}: AgentTabContentProps) {
  const threadItems = conductorState?.running_thread ?? [];
  const lastFive = threadItems.slice(-5).reverse();

  const meshNodes = Array.from(
    new Map(
      agentMeshMessages.flatMap((m) => [
        [m.from_node_key, { id: m.from_node_key, role: m.from_node_key }],
        [m.to_node_key, { id: m.to_node_key, role: m.to_node_key }],
      ]),
    ).values(),
  );

  const meshEdges = agentMeshMessages.map((m) => ({
    id: m.id,
    from_node_key: m.from_node_key,
    to_node_key: m.to_node_key,
    message_type: m.message_type,
    body: m.body,
  }));

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
      {/* Conductor Thread */}
      <div className="shrink-0 px-4 pt-3 pb-2">
        <p className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-1.5">
          Conductor Thread
        </p>
        <div className="max-h-40 overflow-y-auto flex flex-col gap-1">
          {lastFive.length === 0 && (
            <p className="text-[12px] text-text-muted italic">No conductor activity.</p>
          )}
          {lastFive.map((entry, i) => (
            <div key={i} className="text-[12px] flex gap-2 items-start">
              <span className="font-semibold text-brand shrink-0 capitalize">
                {(entry as { action?: string }).action ?? "event"}
              </span>
              <span className="text-text-secondary leading-snug">
                {(entry as { reason?: string | null; note?: string | null }).reason ??
                  (entry as { note?: string | null }).note ??
                  ""}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-2 flex flex-col gap-3">
        {/* Sub-agent Results */}
        <div>
          <p className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">
            Sub-agent Results ({subAgentResults.length})
          </p>
          {subAgentResults.length === 0 ? (
            <p className="text-[12px] text-text-muted italic">No completed sub-agent tasks yet.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {subAgentResults.map((r) => (
                <SubAgentResultCard key={r.task_id} result={r} />
              ))}
            </div>
          )}
        </div>

        {/* Mesh Graph */}
        <div>
          <p className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">
            Agent Mesh
          </p>
          <div className="rounded-xl border border-border-subtle bg-surface-raised p-2">
            <AgentMeshGraph nodes={meshNodes} edges={meshEdges} />
          </div>
        </div>
      </div>

      {/* Conductor Chat Bar (sticky bottom) */}
      <ConductorChatBar projectId={projectId} onSent={onConductorSent} />
    </div>
  );
}


function UnderlineTab({ value, label }: { value: string; label: string }) {
  return (
    <TabsTrigger
      value={value}
      className="px-0 py-2.5 h-auto text-[13px] font-medium text-text-muted data-active:text-foreground after:bottom-[-1px] after:bg-foreground"
    >
      {label}
    </TabsTrigger>
  );
}

/**
 * Live duration chip for the Hero meta row.
 * Pulls pipeline-stages and shows `耗时 15m 23s` when the pipeline window
 * is known. Hidden while waiting for the first sample so the meta row
 * doesn't bounce.
 */
function HeroDurationBit({
  issueId,
  reloadKey,
}: {
  issueId: string;
  reloadKey?: string | number;
}) {
  const [seconds, setSeconds] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const { getIssuePipelineStages } = await import("@/lib/api");
        const p = await getIssuePipelineStages(issueId);
        if (cancelled) return;
        if (p?.total_duration_seconds != null) {
          setSeconds(p.total_duration_seconds);
        } else if (p?.started_at) {
          const start = new Date(p.started_at).getTime();
          setSeconds(Math.max(0, Math.round((Date.now() - start) / 1000)));
        }
      } catch {
        // silent
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [issueId, reloadKey]);

  if (seconds == null) return null;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-text-muted">耗时</span>
      <b className="font-mono font-medium text-foreground">
        {fmtDurationShort(seconds)}
      </b>
    </span>
  );
}

function fmtDurationShort(s: number): string {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return r ? `${m}m ${String(r).padStart(2, "0")}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

/**
 * Render an issue title, highlighting code-like segments
 * (HTTP verbs + paths, `code`-quoted snippets) in mono + brand color.
 *
 * Matches the design's hero where `GET /api/echo` reads as a callout.
 */
function renderTitleWithMono(title: string): React.ReactNode {
  const pattern =
    /(`[^`]+`|\b(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+\/[\w\-/]+|\/[\w\-/]+(?:\.[A-Za-z0-9]+)?)/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(title)) !== null) {
    if (match.index > lastIndex) {
      parts.push(title.slice(lastIndex, match.index));
    }
    const raw = match[0];
    const text = raw.startsWith("`") ? raw.slice(1, -1) : raw;
    parts.push(
      <span
        key={`m-${match.index}`}
        className="font-mono font-semibold text-brand-strong"
      >
        {text}
      </span>,
    );
    lastIndex = match.index + raw.length;
  }
  if (lastIndex < title.length) {
    parts.push(title.slice(lastIndex));
  }
  return parts.length > 0 ? parts : title;
}
