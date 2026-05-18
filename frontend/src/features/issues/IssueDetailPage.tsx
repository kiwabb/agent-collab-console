"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, Circle, GitBranch, GitFork, MessageSquarePlus, Loader2, ChevronDown, ChevronUp } from "lucide-react";
import { useI18n } from "@/providers/I18nProvider";
import {
  forkCodexIssue,
  approveCodexIssuePlan,
  getCodexIssue,
  getCodexIssueChecklist,
  qaReviewCodexIssue,
  steerCodexIssue,
  type IssueChecklist,
} from "@/lib/api";
import type { CodexIssue } from "@/lib/types";
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
import { IssueNarrativeTimeline } from "./components/IssueNarrativeTimeline";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

interface Props {
  issueId: string;
}

const TABS = ["dag", "tasks", "artifacts", "diff"] as const;
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
  const [checklistExpanded, setChecklistExpanded] = useState<boolean | null>(null);
  const [qaRejectDraft, setQaRejectDraft] = useState("");
  const [qaReviewBusy, setQaReviewBusy] = useState<"approve" | "reject" | null>(null);
  const [conductorDecision, setConductorDecision] = useState<{
    action: string;
    reason?: string;
    note?: string | null;
    role?: string;
    receivedAt: number;
  } | null>(null);

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
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-8 py-3.5 border-b border-border-subtle bg-surface z-10 relative shadow-sm">
        <div className="flex flex-col gap-3 max-w-6xl w-full mx-auto">
          {/* Top Row: Meta */}
          <div className="flex items-center gap-2 text-[12px] font-mono text-text-muted">
            <StatusBadge kind={kind} label={statusLabel} className="mr-1 shadow-sm" />
            <span>{t("issue.metaLabel")}</span>
            <span className="text-border-subtle">/</span>
            <span className="text-foreground font-semibold">{issueId.slice(0, 8)}</span>
            {issue?.git_branch && (
              <>
                <span className="text-border-subtle">/</span>
                <span className="flex items-center gap-1.5 text-brand bg-brand/10 border border-brand/20 px-2 py-0.5 rounded-md">
                  <GitBranch size={12} />
                  {issue.git_branch}
                </span>
              </>
            )}
            <div className="ml-auto flex items-center gap-3">
              <span className="text-[11px] text-text-muted uppercase tracking-wider">
                {t("issue.phaseLabel")} <span className="text-foreground font-bold">{issue?.current_phase ?? "—"}</span>
              </span>
              {issue?.created_at && (
                <>
                  <span className="text-border-subtle">·</span>
                  <span className="text-[11px] text-text-muted">
                    {t("issue.createdAt", { time: new Date(issue.created_at).toLocaleString() })}
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Bottom Row: Title and Actions */}
          <div className="flex items-center justify-between gap-4 mt-1">
            <h1 className="text-2xl font-bold tracking-tight truncate text-foreground leading-tight">
              {issue?.title ?? t("issue.titleFallback")}
            </h1>
            <div className="flex items-center gap-2.5 shrink-0">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleFork()}
                disabled={forking || !issue?.git_worktree_path}
                title={t("issue.forkHelp")}
                className="gap-2 h-8 px-3.5 text-[12px] font-medium shadow-sm hover:shadow-md transition-shadow"
              >
                {forking ? <Loader2 size={14} className="animate-spin" /> : <GitFork size={14} />}
                {t("issue.fork")}
              </Button>
              <Button
                size="sm"
                onClick={() => setSteerOpen(true)}
                disabled={!issue?.git_worktree_path}
                title={issue?.git_worktree_path ? t("issue.steerHelp") : t("issue.noActiveWorktree")}
                className="gap-2 h-8 px-3.5 text-[12px] font-semibold bg-brand hover:bg-brand-strong text-black shadow-sm shadow-brand/20 hover:shadow-md transition-all"
              >
                <MessageSquarePlus size={14} />
                {t("issue.steer")}
              </Button>
            </div>
          </div>
        </div>
      </div>

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

        {/* A4: narrative timeline distilled from each role's task.result */}
        <IssueNarrativeTimeline issueId={issueId} reloadKey={issue?.updated_at ?? undefined} />

        {checklist && checklist.criteria.length > 0 && (() => {
          const hasUncovered = checklist.criteria.some(c => !c.covered);
          const isChecklistExpanded = checklistExpanded !== null ? checklistExpanded : hasUncovered;
          return (
            <div className="px-8 mt-3">
              <div className="w-full">
                <div className="rounded-xl border border-border-subtle bg-surface shadow-sm overflow-hidden">
                  <div 
                    role="button"
                    onClick={() => setChecklistExpanded(!isChecklistExpanded)}
                    className="px-4 py-3 border-b border-border-subtle bg-surface-hover flex items-center justify-between cursor-pointer select-none hover:bg-surface-hover/80 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <span className="font-bold text-[12px] uppercase tracking-wider text-foreground">{t("issue.checklist")}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-32 h-1.5 bg-border-subtle rounded-full overflow-hidden shadow-inner">
                          <div 
                            className="h-full bg-success transition-all duration-500 ease-out" 
                            style={{ width: `${Math.round((checklist.criteria.filter(c => c.covered).length / checklist.criteria.length) * 100)}%` }}
                          />
                        </div>
                        <span className="text-[11px] font-mono text-text-muted">
                          {checklist.criteria.filter((c) => c.covered).length}/{checklist.criteria.length}
                        </span>
                      </div>
                    </div>
                    <div className="text-text-muted">
                      {isChecklistExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </div>
                  </div>
                  {isChecklistExpanded && (
                    <ul className="divide-y divide-border-subtle">
                      {checklist.criteria.slice(0, 6).map((c, i) => (
                        <li
                          key={i}
                          className="flex items-center gap-3 px-4 py-2.5 text-[13px] transition-colors hover:bg-surface-hover/50"
                        >
                          {c.covered ? (
                            <CheckCircle2 size={16} className="text-success shrink-0" />
                          ) : (
                            <Circle size={16} className="text-border-strong shrink-0" />
                          )}
                          <span className={cn("flex-1", c.covered ? "text-text-secondary line-through" : "text-foreground font-medium")}>
                            {c.text}
                          </span>
                          {c.source && (
                            <span className="text-[10px] font-mono uppercase tracking-wider text-text-muted/80 bg-surface-raised px-1.5 py-0.5 rounded border border-border-subtle shrink-0">
                              {c.source}
                            </span>
                          )}
                        </li>
                      ))}
                      {checklist.criteria.length > 6 && (
                        <li className="px-4 py-2.5 text-[12px] font-medium text-text-muted bg-surface-hover flex items-center gap-2">
                          <div className="w-4 h-4 flex items-center justify-center shrink-0">
                            <span className="block w-1 h-1 bg-text-muted rounded-full opacity-50 shadow-[4px_0_0_0_currentColor,-4px_0_0_0_currentColor]" />
                          </div>
                          {t("issue.checklistMore", { count: checklist.criteria.length - 6 })}
                        </li>
                      )}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          );
        })()}

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

      {/* Tabs */}
      <Tabs value={tab} onValueChange={onTabChange} className="flex flex-col flex-1 min-h-0 mt-2">
        <TabsList
          variant="line"
          className="px-6 pt-2 self-stretch border-b border-border-subtle gap-6 shrink-0"
        >
          <UnderlineTab value="dag" label="DAG" />
          <UnderlineTab value="tasks" label={t("issue.tab.tasksRuns")} />
          <UnderlineTab value="artifacts" label={t("console.artifacts")} />
          <UnderlineTab value="diff" label={t("issue.tab.diffMerge")} />
        </TabsList>
        <div className="flex flex-col flex-1 min-h-0">
          <TabsContent value="dag" className="m-0 h-full flex flex-col min-h-0 flex-1">
            <DagTab issueId={issueId} />
          </TabsContent>
          <TabsContent value="tasks" className="m-0 h-full flex flex-col min-h-0 flex-1">
            <TasksRunsTab issueId={issueId} issue={issue} />
          </TabsContent>
          <TabsContent value="artifacts" className="m-0 h-full flex flex-col min-h-0 flex-1">
            <ArtifactsTab issueId={issueId} active={tab === "artifacts"} issue={issue} />
          </TabsContent>
          <TabsContent value="diff" className="m-0 h-full flex flex-col min-h-0 flex-1 overflow-y-auto">
            <DiffMergeTab issueId={issueId} issue={issue} active={tab === "diff"} />
          </TabsContent>
        </div>
      </Tabs>
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
