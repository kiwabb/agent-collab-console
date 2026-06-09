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
import {
  EmptyStateAction,
  InteractionEmptyState,
} from "@/components/ui/interaction-empty-state";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { useToast } from "@/components/ui/toast";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import { cn } from "@/lib/utils";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { PageFrame } from "@/features/workbench/components/PageFrame";
import { useI18n } from "@/providers/I18nProvider";

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
  const { t } = useI18n();
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
          title: t("approvals.toast.loadFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [addToast, t],
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
          title: decision === "approve" ? t("approvals.toast.approved") : t("approvals.toast.sentBack"),
        });
        await load("refresh");
      } catch (err) {
        addToast({
          type: "error",
          title: t("approvals.toast.reviewFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setBusyId(null);
      }
    },
    [addToast, load, t],
  );

  const handleAnswerQuestion = useCallback(
    async (task: CodexTask, answer: string) => {
      const trimmed = answer.trim();
      if (!trimmed) {
        addToast({ type: "error", title: t("approvals.toast.answerEmpty") });
        return;
      }
      setBusyId(task.id);
      try {
        await answerCodexTaskClarification(task.id, trimmed);
        addToast({ type: "success", title: t("approvals.toast.answerSent") });
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
          title: t("approvals.toast.answerFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setBusyId(null);
      }
    },
    [addToast, load, router, t],
  );

  const handleResolveTool = useCallback(
    async (approval: Approval, decision: "accept" | "decline") => {
      setBusyId(approval.id);
      try {
        await resolveApproval(approval.id, decision, null);
        addToast({
          type: "success",
          title: decision === "accept" ? t("approvals.toast.approved") : t("approvals.toast.declined"),
        });
        await load("refresh");
      } catch (err) {
        addToast({
          type: "error",
          title: t("approvals.toast.resolveFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setBusyId(null);
      }
    },
    [addToast, load, t],
  );

  return (
    <PageFrame
      eyebrow={t("approvals.eyebrow")}
      title={t("approvals.title")}
      description={t("approvals.description")}
      actions={(
        <Button
          size="sm"
          variant="outline"
          disabled={refreshing}
          data-density={refreshing ? "approvals-refresh-tool" : "approvals-refresh"}
          className={cn(refreshing && "motion-essential")}
          onClick={() => void load("refresh")}
        >
          {refreshing ? (
            <AgentThinkingIndicator phase="tool" size={12} />
          ) : (
            <RefreshCw size={12} />
          )}
          {t("approvals.refresh")}
        </Button>
      )}
      contentClassName="space-y-5"
    >
      <div className="space-y-5">
        <div className="enterprise-card flex items-center gap-1 overflow-x-auto rounded-2xl px-2">
          <TabBtn active={tab === "all"} onClick={() => setTab("all")}>
            {t("approvals.tab.all")} <Pill>{total}</Pill>
          </TabBtn>
          <TabBtn active={tab === "issues"} onClick={() => setTab("issues")}>
            {t("approvals.tab.issues")} <Pill>{totals.issues}</Pill>
          </TabBtn>
          <TabBtn active={tab === "reviews"} onClick={() => setTab("reviews")}>
            {t("approvals.tab.reviews")} <Pill>{totals.reviews}</Pill>
          </TabBtn>
          <TabBtn active={tab === "questions"} onClick={() => setTab("questions")}>
            {t("approvals.tab.questions")} <Pill>{totals.questions}</Pill>
          </TabBtn>
          <TabBtn active={tab === "qa_passed"} onClick={() => setTab("qa_passed")}>
            {t("approvals.tab.qaPassed")} <Pill>{totals.qa_passed}</Pill>
          </TabBtn>
          <TabBtn active={tab === "tools"} onClick={() => setTab("tools")}>
            {t("approvals.tab.tools")} <Pill>{totals.tools}</Pill>
          </TabBtn>
        </div>

        {loading ? (
          <InteractionEmptyState
            tone="loading"
            title={t("approvals.loadingTitle")}
            description={t("approvals.loadingDescription")}
          />
        ) : total === 0 ? (
          <InteractionEmptyState
            title={t("approvals.emptyTitle")}
            description={t("approvals.emptyDescription")}
            action={
              <EmptyStateAction onClick={() => router.push("/")}>
                {t("approvals.openInbox")}
              </EmptyStateAction>
            }
          />
        ) : (
          <div className="space-y-6">
            {visible.length > 0 && (
              <Section title={t("approvals.section.issues")} count={visible.length}>
                <ul className="enterprise-panel divide-y divide-border-subtle rounded-2xl overflow-hidden">
                  {visible.map((issue) => (
                    <RowCard
                      key={issue.id}
                      title={issue.title || issue.id.slice(0, 8)}
                      subtitle={t("approvals.issueSubtitle", { phase: issue.current_phase ?? "—" })}
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
              <Section title={t("approvals.section.questions")} count={visibleQuestions.length}>
                <ul className="space-y-2">
                  {visibleQuestions.map((task) => {
                    const question = (task.review_comment || "").slice(CLARIFY_PREFIX.length);
                    return (
                      <li
                        key={task.id}
                        className="enterprise-card rounded-2xl border-brand/40 bg-brand/5 p-4"
                      >
                        <div className="flex items-baseline gap-2">
                          <StatusBadge kind="awaiting" label={t("approvals.agentAsks", { role: task.role ?? "agent" })} />
                          <span className="text-[13px] font-semibold truncate flex-1">
                            {task.title || task.id.slice(0, 8)}
                          </span>
                          {task.issue_id && (
                            <button
                              type="button"
                              onClick={() => router.push(`/issues/${task.issue_id}?tab=tasks&taskId=${task.id}`)}
                              className="text-[11px] text-brand hover:underline"
                            >
                              {t("approvals.openTask")}
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
              <Section title={t("approvals.section.reviews")} count={visibleReviews.length}>
                <ul className="enterprise-panel divide-y divide-border-subtle rounded-2xl overflow-hidden">
                  {visibleReviews.map((task) => (
                    <RowCard
                      key={task.id}
                      title={task.title || task.id.slice(0, 8)}
                      subtitle={t("approvals.taskSubtitle", { role: task.role ?? "general", executor: task.executor ?? "—" })}
                      kindLabel={t("approvals.kindAwaitingReview")}
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
              <Section title={t("approvals.section.qaPassed")} count={visibleQaPassed.length}>
                <ul className="enterprise-panel divide-y divide-border-subtle rounded-2xl overflow-hidden">
                  {visibleQaPassed.map((issue) => (
                    <RowCard
                      key={issue.id}
                      title={issue.title || issue.id.slice(0, 8)}
                      subtitle={t("approvals.issueSubtitle", { phase: issue.current_phase ?? "—" })}
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
              <Section title={t("approvals.section.tools")} count={visibleTools.length}>
                <ul className="enterprise-panel divide-y divide-border-subtle rounded-2xl overflow-hidden">
                  {visibleTools.map((approval) => (
                    <RowCard
                      key={approval.id}
                      title={approval.action || t("approvals.toolActionFallback")}
                      subtitle={t("approvals.toolSubtitle", { session: approval.session_id.slice(0, 8) })}
                      kindLabel={t("approvals.kindNeedsPermission")}
                      kind="awaiting"
                      meta={
                        <span className="font-mono text-[11px] text-text-muted">
                          {t("approvals.toolMeta", { task: approval.task_id.slice(0, 8) })}
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
    </PageFrame>
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
  const { t } = useI18n();

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
            data-density={busy ? "approvals-row-approve-tool" : "approvals-row-approve"}
            className={cn("bg-success text-black hover:bg-success/90", busy && "motion-essential")}
          >
            {busy ? (
              <AgentThinkingIndicator phase="tool" size={12} />
            ) : (
              <CheckCircle2 size={12} />
            )}
            <span className="ml-1">{t("approvals.approve")}</span>
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
            <span className="ml-1">{t("approvals.reject")}</span>
          </Button>
        )}
        {action.open && (
          <Button size="sm" variant="ghost" onClick={action.open}>
            {t("approvals.open")}
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
  const { t } = useI18n();
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
        placeholder={t("approvals.answerPlaceholder")}
        className="bg-surface-input border-border-subtle h-9 text-[13px]"
        disabled={disabled}
        autoFocus={false}
      />
      <Button
        type="submit"
        size="sm"
        disabled={disabled || !draft.trim()}
        data-density={disabled ? "approvals-answer-thinking" : "approvals-answer"}
        className={cn("bg-brand hover:bg-brand-strong text-black font-semibold", disabled && "motion-essential")}
      >
        {disabled ? (
          <AgentThinkingIndicator phase="thinking" size={12} />
        ) : (
          t("approvals.sendAnswer")
        )}
      </Button>
    </form>
  );
}

export const _UNUSED = InboxIcon; // tree-shake guard
