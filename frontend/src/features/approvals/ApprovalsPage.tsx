"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  XCircle,
  Inbox as InboxIcon,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import {
  answerCodexTaskClarification,
  getCodexIssues,
  getCodexTasks,
  getPendingApprovals,
  resolveApproval,
  reviewCodexTask,
} from "@/lib/api";
import type { Approval, CodexIssue, CodexTask } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import { cn } from "@/lib/utils";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

const CLARIFY_PREFIX = "[CLARIFY] ";

type Tab = "all" | "issues" | "reviews" | "questions" | "qa_passed" | "tools";

interface RowAction {
  approve?: () => Promise<void>;
  reject?: () => Promise<void>;
  open?: () => void;
}

export function ApprovalsPage() {
  const router = useRouter();
  const { addToast } = useToast();
  const [issues, setIssues] = useState<CodexIssue[]>([]);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [tools, setTools] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<Tab>("all");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(
    async (mode: "initial" | "refresh" = "refresh") => {
      if (mode === "initial") setLoading(true);
      else setRefreshing(true);
      try {
        const [iss, ts, app] = await Promise.all([
          getCodexIssues(null, null),
          getCodexTasks(null, null),
          getPendingApprovals(),
        ]);
        setIssues(iss);
        setTasks(ts);
        setTools(app.pending);
      } catch (err) {
        addToast({
          type: "error",
          title: "Failed to load approvals",
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [addToast],
  );

  useEffect(() => {
    void load("initial");
    // Fallback poll, lengthened now that events do most of the heavy lifting.
    const id = window.setInterval(() => void load("refresh"), 30000);
    return () => window.clearInterval(id);
  }, [load]);

  // Event-driven refresh. Approvals page has no workspace scope, so
  // ExecutionProcessesProvider now consumes the global WS event stream
  // (/api/ws/events) which surfaces every event_bus event. Refetch whenever
  // anything that could land in our inbox happens.
  useBusEventEffect({
    match: busEventMatchers.typeIn(
      "task_status",
      "task_created",
      "approval_required",
      "approval_resolved",
      "issue_updated",
      "issue_created",
      "issue_merged",
      "issue_abandoned",
    ),
    onEvent: () => { void load("refresh"); },
    throttleMs: 800,
  });

  const issueApprovals = useMemo(
    () =>
      issues.filter(
        (i) => i.status === "awaiting_approval" || i.status === "review",
      ),
    [issues],
  );

  const allAwaitingReview = useMemo(
    () => tasks.filter((t) => t.status === "awaiting_review"),
    [tasks],
  );

  const clarificationTasks = useMemo(
    () =>
      allAwaitingReview.filter((t) =>
        (t.review_comment || "").startsWith(CLARIFY_PREFIX),
      ),
    [allAwaitingReview],
  );

  const taskReviews = useMemo(
    () =>
      allAwaitingReview.filter(
        (t) => !(t.review_comment || "").startsWith(CLARIFY_PREFIX),
      ),
    [allAwaitingReview],
  );

  const qaPassedIssues = useMemo(
    () => issues.filter((i) => i.status === "awaiting_review"),
    [issues],
  );

  const totals = {
    issues: issueApprovals.length,
    reviews: taskReviews.length,
    questions: clarificationTasks.length,
    qa_passed: qaPassedIssues.length,
    tools: tools.length,
  };
  const total = totals.issues + totals.reviews + totals.questions + totals.qa_passed + totals.tools;

  const visible = tab === "all" || tab === "issues" ? issueApprovals : [];
  const visibleReviews = tab === "all" || tab === "reviews" ? taskReviews : [];
  const visibleQuestions = tab === "all" || tab === "questions" ? clarificationTasks : [];
  const visibleQaPassed = tab === "all" || tab === "qa_passed" ? qaPassedIssues : [];
  const visibleTools = tab === "all" || tab === "tools" ? tools : [];

  const handleReviewTask = useCallback(
    async (task: CodexTask, decision: "approve" | "reject") => {
      setBusyId(task.id);
      try {
        await reviewCodexTask(task.id, decision, null);
        addToast({
          type: "success",
          title: decision === "approve" ? "Approved" : "Sent back for rework",
        });
        await load("refresh");
      } catch (err) {
        addToast({
          type: "error",
          title: "Review failed",
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setBusyId(null);
      }
    },
    [addToast, load],
  );

  const handleAnswerQuestion = useCallback(
    async (task: CodexTask, answer: string) => {
      const trimmed = answer.trim();
      if (!trimmed) {
        addToast({ type: "error", title: "Answer cannot be empty" });
        return;
      }
      setBusyId(task.id);
      try {
        await answerCodexTaskClarification(task.id, trimmed);
        addToast({ type: "success", title: "Answer sent — agent re-dispatched" });
        // D2: hop back to the issue so the user can watch the agent
        // re-run with their answer threaded in, instead of staying on
        // the approvals inbox.
        if (task.issue_id) {
          setTimeout(
            () => router.push(`/issues/${task.issue_id}?tab=tasks&taskId=${task.id}`),
            500,
          );
        } else {
          await load("refresh");
        }
      } catch (err) {
        addToast({
          type: "error",
          title: "Failed to send answer",
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setBusyId(null);
      }
    },
    [addToast, load, router],
  );

  const handleResolveTool = useCallback(
    async (approval: Approval, decision: "accept" | "decline") => {
      setBusyId(approval.id);
      try {
        await resolveApproval(approval.id, decision, null);
        addToast({
          type: "success",
          title: decision === "accept" ? "Approved" : "Declined",
        });
        await load("refresh");
      } catch (err) {
        addToast({
          type: "error",
          title: "Resolve failed",
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setBusyId(null);
      }
    },
    [addToast, load],
  );

  return (
    <div className="min-h-full">
      <div className="relative overflow-hidden border-b border-border-subtle">
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.35] pointer-events-none"
          style={{
            background:
              "radial-gradient(900px 300px at 12% -10%, rgba(96,165,250,0.25), transparent 60%), radial-gradient(700px 240px at 90% -10%, rgba(230,149,82,0.18), transparent 60%)",
          }}
        />
        <div className="relative px-8 pt-7 pb-6 max-w-[1280px] mx-auto">
          <div className="flex items-center gap-3 mb-2">
            <span className="size-9 rounded-xl bg-gradient-to-br from-info to-info/60 flex items-center justify-center shadow-lg shadow-info/30">
              <ShieldCheck size={18} className="text-black" />
            </span>
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-bold tracking-tight">Approvals</h1>
              <p className="text-[12px] text-text-muted">
                Review the things waiting on you across every project.
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={refreshing}
              onClick={() => void load("refresh")}
            >
              <RefreshCw size={12} className={cn("mr-1.5", refreshing && "animate-spin")} />
              Refresh
            </Button>
          </div>
        </div>
      </div>

      <div className="px-8 py-6 max-w-[1280px] mx-auto space-y-5">
        <div className="flex items-center gap-1 border-b border-border-subtle">
          <TabBtn active={tab === "all"} onClick={() => setTab("all")}>
            All <Pill>{total}</Pill>
          </TabBtn>
          <TabBtn active={tab === "issues"} onClick={() => setTab("issues")}>
            Issues <Pill>{totals.issues}</Pill>
          </TabBtn>
          <TabBtn active={tab === "reviews"} onClick={() => setTab("reviews")}>
            Task reviews <Pill>{totals.reviews}</Pill>
          </TabBtn>
          <TabBtn active={tab === "questions"} onClick={() => setTab("questions")}>
            Agent questions <Pill>{totals.questions}</Pill>
          </TabBtn>
          <TabBtn active={tab === "qa_passed"} onClick={() => setTab("qa_passed")}>
            QA passed <Pill>{totals.qa_passed}</Pill>
          </TabBtn>
          <TabBtn active={tab === "tools"} onClick={() => setTab("tools")}>
            Tool calls <Pill>{totals.tools}</Pill>
          </TabBtn>
        </div>

        {loading ? (
          <div className="py-16 text-center text-sm text-text-muted">Loading…</div>
        ) : total === 0 ? (
          <div className="py-20 text-center">
            <div className="inline-flex size-12 rounded-full bg-success/10 items-center justify-center mb-3">
              <CheckCircle2 size={20} className="text-success" />
            </div>
            <h2 className="text-base font-semibold">Inbox zero</h2>
            <p className="text-sm text-text-muted mt-1">
              Nothing is waiting on a human right now.
            </p>
          </div>
        ) : (
          <div className="space-y-6">
            {visible.length > 0 && (
              <Section title="Issues awaiting approval" count={visible.length}>
                <ul className="divide-y divide-border-subtle rounded-xl border border-border-subtle overflow-hidden">
                  {visible.map((issue) => (
                    <RowCard
                      key={issue.id}
                      title={issue.title || issue.id.slice(0, 8)}
                      subtitle={`Issue · phase ${issue.current_phase ?? "—"}`}
                      kindLabel={(issue.status ?? "—").replace(/_/g, " ")}
                      kind={inferStatusKind(issue.status)}
                      meta={
                        issue.git_branch ? (
                          <span className="font-mono text-[11px] text-text-muted truncate">
                            {issue.git_branch}
                          </span>
                        ) : null
                      }
                      busy={busyId === issue.id}
                      action={{
                        open: () => router.push(`/issues/${issue.id}?tab=diff`),
                      }}
                    />
                  ))}
                </ul>
              </Section>
            )}

            {visibleQuestions.length > 0 && (
              <Section title="Agent questions awaiting your answer" count={visibleQuestions.length}>
                <ul className="space-y-2">
                  {visibleQuestions.map((task) => {
                    const question = (task.review_comment || "").slice(CLARIFY_PREFIX.length);
                    return (
                      <li
                        key={task.id}
                        className="rounded-xl border border-brand/40 bg-brand/5 p-4"
                      >
                        <div className="flex items-baseline gap-2">
                          <StatusBadge kind="awaiting" label={`${task.role ?? "agent"} asks`} />
                          <span className="text-[13px] font-semibold truncate flex-1">
                            {task.title || task.id.slice(0, 8)}
                          </span>
                          {task.issue_id && (
                            <button
                              type="button"
                              onClick={() => router.push(`/issues/${task.issue_id}?tab=tasks&taskId=${task.id}`)}
                              className="text-[11px] text-brand hover:underline"
                            >
                              open task →
                            </button>
                          )}
                        </div>
                        <p className="mt-2 text-[13px] text-foreground/90 leading-relaxed">
                          {question}
                        </p>
                        <AnswerInline
                          disabled={busyId === task.id}
                          onSubmit={(answer) => handleAnswerQuestion(task, answer)}
                        />
                      </li>
                    );
                  })}
                </ul>
              </Section>
            )}

            {visibleReviews.length > 0 && (
              <Section title="Tasks awaiting review" count={visibleReviews.length}>
                <ul className="divide-y divide-border-subtle rounded-xl border border-border-subtle overflow-hidden">
                  {visibleReviews.map((task) => (
                    <RowCard
                      key={task.id}
                      title={task.title || task.id.slice(0, 8)}
                      subtitle={`Task · ${task.role ?? "general"} · ${task.executor ?? "—"}`}
                      kindLabel="awaiting review"
                      kind="awaiting"
                      busy={busyId === task.id}
                      action={{
                        open: task.issue_id
                          ? () => router.push(`/issues/${task.issue_id}?tab=tasks&taskId=${task.id}`)
                          : undefined,
                        approve: () => handleReviewTask(task, "approve"),
                        reject: () => handleReviewTask(task, "reject"),
                      }}
                    />
                  ))}
                </ul>
              </Section>
            )}

            {visibleQaPassed.length > 0 && (
              <Section title="QA passed" count={visibleQaPassed.length}>
                <ul className="divide-y divide-border-subtle rounded-xl border border-border-subtle overflow-hidden">
                  {visibleQaPassed.map((issue) => (
                    <RowCard
                      key={issue.id}
                      title={issue.title || issue.id.slice(0, 8)}
                      subtitle={`Issue · phase ${issue.current_phase ?? "—"}`}
                      kindLabel={(issue.status ?? "—").replace(/_/g, " ")}
                      kind={inferStatusKind(issue.status)}
                      meta={
                        issue.git_branch ? (
                          <span className="font-mono text-[11px] text-text-muted truncate">
                            {issue.git_branch}
                          </span>
                        ) : null
                      }
                      busy={busyId === issue.id}
                      action={{
                        open: () => router.push(`/issues/${issue.id}`),
                      }}
                    />
                  ))}
                </ul>
              </Section>
            )}

            {visibleTools.length > 0 && (
              <Section title="Tool calls awaiting permission" count={visibleTools.length}>
                <ul className="divide-y divide-border-subtle rounded-xl border border-border-subtle overflow-hidden">
                  {visibleTools.map((approval) => (
                    <RowCard
                      key={approval.id}
                      title={approval.action || "Tool action"}
                      subtitle={`Codex · session ${approval.session_id.slice(0, 8)}`}
                      kindLabel="needs permission"
                      kind="awaiting"
                      meta={
                        <span className="font-mono text-[11px] text-text-muted">
                          task {approval.task_id.slice(0, 8)}
                        </span>
                      }
                      busy={busyId === approval.id}
                      action={{
                        open: () => router.push(`/workspaces/${approval.session_id}`),
                        approve: () => handleResolveTool(approval, "accept"),
                        reject: () => handleResolveTool(approval, "decline"),
                      }}
                    />
                  ))}
                </ul>
              </Section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <h2 className="text-[11px] font-black uppercase tracking-widest text-text-muted">
          {title}
        </h2>
        <span className="text-[11px] tabular-nums text-text-muted">{count}</span>
      </div>
      {children}
    </section>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-3 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors flex items-center gap-1.5",
        active
          ? "text-foreground border-foreground"
          : "text-text-muted border-transparent hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] rounded-full bg-surface-input text-[10px] tabular-nums px-1.5 text-text-muted">
      {children}
    </span>
  );
}

function RowCard({
  title,
  subtitle,
  meta,
  kindLabel,
  kind,
  busy,
  action,
}: {
  title: string;
  subtitle: string;
  meta?: React.ReactNode;
  kindLabel: string;
  kind: ReturnType<typeof inferStatusKind>;
  busy: boolean;
  action: RowAction;
}) {
  return (
    <li className="grid grid-cols-[1fr_auto] gap-3 px-4 py-3 items-center hover:bg-surface-hover transition-colors">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold truncate">{title}</span>
          <StatusBadge kind={kind} label={kindLabel} />
        </div>
        <div className="flex items-center gap-3 mt-1 text-[11px] text-text-muted">
          <span>{subtitle}</span>
          {meta}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {action.approve && (
          <Button
            size="sm"
            disabled={busy}
            onClick={() => void action.approve!()}
            className="bg-success text-black hover:bg-success/90"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
            <span className="ml-1">Approve</span>
          </Button>
        )}
        {action.reject && (
          <Button
            size="sm"
            disabled={busy}
            variant="outline"
            onClick={() => void action.reject!()}
          >
            <XCircle size={12} />
            <span className="ml-1">Reject</span>
          </Button>
        )}
        {action.open && (
          <Button size="sm" variant="ghost" onClick={action.open}>
            Open
          </Button>
        )}
      </div>
    </li>
  );
}

function AnswerInline({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (answer: string) => void;
}) {
  const [draft, setDraft] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!draft.trim()) return;
        onSubmit(draft);
        setDraft("");
      }}
      className="mt-3 flex gap-2 items-stretch"
    >
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="Type your answer and press enter…"
        className="bg-surface-input border-border-subtle h-9 text-[13px]"
        disabled={disabled}
        autoFocus={false}
      />
      <Button
        type="submit"
        size="sm"
        disabled={disabled || !draft.trim()}
        className="bg-brand hover:bg-brand-strong text-black font-semibold"
      >
        {disabled ? <Loader2 size={12} className="animate-spin" /> : "Send answer"}
      </Button>
    </form>
  );
}

export const _UNUSED = InboxIcon; // tree-shake guard
