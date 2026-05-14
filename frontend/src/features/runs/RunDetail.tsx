"use client";

import type { ExecutionProcess, CodexTask, CodexTaskMessage, LogEvent, RuntimeCatalog, RunMode } from "@/lib/types";
import { RotateCcw, Trash2, Send, Terminal, MessageSquare, Play, Activity, AlertCircle, Check } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { useExecutionProcessMessageStream } from "@/hooks/useExecutionProcessMessageStream";
import { useExecutionProcessLogStream } from "@/hooks/useExecutionProcessLogStream";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { normalizeLogs } from "@/lib/codexLogNormalizer";
import { ExecutionConfigSelector, getFallbackConfig, type ExecutionConfigValue } from "@/components/runtime/ExecutionConfigSelector";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { renderMessageWithLinks } from "@/lib/utils";
import { shouldShowTopErrorCard } from "@/lib/runDetailErrorState";
import { MessageMarkdown } from "./MessageMarkdown";
import { ToolBlock } from "./toolBlocks/ToolBlocks";

interface RunDetailProps {
  process: ExecutionProcess | null;
  isLoadingProcess?: boolean;
  taskMeta?: CodexTask | null;
  task: CodexTaskMessage[];
  logs: LogEvent[];
  isLoadingLogs: boolean;
  isLoadingMessages: boolean;
  onRunInitial?: (executor: "codex" | "claude", provider: string | null, model: string | null) => void;
  onRunAgain: (executor: "codex" | "claude", provider: string | null, model: string | null) => void;
  onDelete: () => void;
  onSendMessage: (content: string, mode: RunMode) => void;
  allTasks?: CodexTask[];
  selectedExecutor?: "codex" | "claude";
  selectedProvider?: string | null;
  selectedModel?: string | null;
  onExecutorChange?: (executor: "codex" | "claude", provider: string | null, model: string | null) => void;
  showTransitionToArchitecture?: boolean;
  canTransitionToArchitecture?: boolean;
  isTransitioningToArchitecture?: boolean;
  onTransitionToArchitecture?: () => Promise<void> | void;
  showTransitionToDevelopment?: boolean;
  canTransitionToDevelopment?: boolean;
  isTransitioningToDevelopment?: boolean;
  onTransitionToDevelopment?: () => Promise<void> | void;
  showTransitionToTesting?: boolean;
  canTransitionToTesting?: boolean;
  isTransitioningToTesting?: boolean;
  onTransitionToTesting?: () => Promise<void> | void;
  qaReportStatus?: "passed" | "failed" | "blocked" | "needs_follow_up" | null;
  onViewQaReport?: () => void;
  lastResolvedMode?: "chat" | "refine" | null;
  onSubmitForReview?: () => Promise<void> | void;
  onReview?: (decision: "approve" | "reject", comment: string) => Promise<void> | void;
  onTerminate?: () => Promise<void> | void;
  catalog?: RuntimeCatalog | null;
}

function getDevelopmentTaskUnlockStatus(task: CodexTask, allTasks: CodexTask[]): { unlocked: boolean; reason: string | null } {
  if (task.phase !== "development" || task.sequence_index == null) {
    return { unlocked: true, reason: null };
  }
  if (task.sequence_index === 0) {
    return { unlocked: true, reason: null };
  }
  const prevIndex = task.sequence_index - 1;
  const prevTask = allTasks.find(
    (t) => t.phase === "development" && t.sequence_index === prevIndex && t.sequence_group === task.sequence_group
  );
  if (!prevTask) {
    return { unlocked: false, reason: "task.sequence.blocked" };
  }
  if (prevTask.status !== "done") {
    return { unlocked: false, reason: "task.sequence.blocked" };
  }
  return { unlocked: true, reason: null };
}

export function RunDetail({
  process,
  isLoadingProcess = false,
  taskMeta,
  task,
  logs,
  isLoadingLogs,
  isLoadingMessages,
  onRunInitial,
  onRunAgain,
  onDelete,
  onSendMessage,
  allTasks = [],
  selectedExecutor = "codex",
  selectedProvider = null,
  selectedModel = null,
  onExecutorChange,
  showTransitionToArchitecture,
  canTransitionToArchitecture,
  isTransitioningToArchitecture,
  onTransitionToArchitecture,
  showTransitionToDevelopment,
  canTransitionToDevelopment,
  isTransitioningToDevelopment,
  onTransitionToDevelopment,
  showTransitionToTesting,
  canTransitionToTesting,
  isTransitioningToTesting,
  onTransitionToTesting,
  qaReportStatus,
  onViewQaReport,
  lastResolvedMode,
  onSubmitForReview,
  onReview,
  onTerminate,
  catalog,
}: RunDetailProps) {
  const { t } = useI18n();
  const [message, setMessage] = useState("");
  const [runMode, setRunMode] = useState<RunMode>("auto");
  const [showRerunConfirm, setShowRerunConfirm] = useState(false);
  // Auto-scroll the messages / logs panes to the bottom when new content arrives.
  // We scroll the container itself (not via scrollIntoView on a sentinel) because:
  //   - sentinel-based scrollIntoView is smooth-animated and gets cut off by
  //     subsequent re-renders (selectedProcessId switch fires several renders in a row)
  //   - direct scrollTop assignment inside requestAnimationFrame guarantees the
  //     final paint frame ends at the bottom regardless of intermediate renders
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);
  const logsContainerRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = useCallback((el: HTMLElement | null, smooth = true) => {
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
      // One more frame to defeat layout shifts from fade-in animations.
      requestAnimationFrame(() => {
        el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
      });
    });
  }, []);
  const [reviewComment, setReviewComment] = useState("");
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);
  const baseExecutionConfig = useMemo<ExecutionConfigValue>(() => getFallbackConfig(
    catalog || null,
    selectedExecutor,
    selectedProvider,
    selectedModel,
  ), [catalog, selectedExecutor, selectedProvider, selectedModel]);
  const [executionConfig, setExecutionConfig] = useState<ExecutionConfigValue>(baseExecutionConfig);

  useEffect(() => {
    setExecutionConfig(baseExecutionConfig);
  }, [baseExecutionConfig]);

  // Token-level streaming: subscribe to live message + log WS.
  // Initial snapshot still comes via REST (props `logs` / `task`); stream events
  // are merged in to give a live typewriter UX without a refresh.
  const liveStream = useExecutionProcessMessageStream(process?.id ?? null);
  const liveLogStream = useExecutionProcessLogStream(process?.id ?? null);
  const mergedLogs = useMemo(() => {
    const byId = new Map<string, typeof logs[number]>();
    for (const l of logs) if (l?.id) byId.set(l.id, l);
    for (const l of liveLogStream.logs) if (l?.id) byId.set(l.id, l);
    return Array.from(byId.values());
  }, [logs, liveLogStream.logs]);
  const mergedMessages = useMemo(() => {
    const byId = new Map<string, typeof task[number]>();
    for (const m of task) if (m?.id) byId.set(m.id, m);
    for (const m of liveStream.messages) if (m?.id) byId.set(m.id, m);
    return Array.from(byId.values());
  }, [task, liveStream.messages]);
  const normalizedLogs = useMemo(() => normalizeLogs(mergedLogs), [mergedLogs]);

  // Smoothly scroll when full messages arrive (user send, agent reply commit).
  useEffect(() => {
    scrollToBottom(messagesContainerRef.current, true);
  }, [mergedMessages.length, scrollToBottom]);

  // Token-streaming deltas: tight loop, use instant scroll (smooth would
  // queue + cancel itself dozens of times per second and look jittery).
  useEffect(() => {
    scrollToBottom(messagesContainerRef.current, false);
  }, [liveStream.pendingAssistant?.text, scrollToBottom]);

  // Logs stream: line-buffered, smooth is fine.
  useEffect(() => {
    scrollToBottom(logsContainerRef.current, true);
  }, [normalizedLogs.length, scrollToBottom]);

  // EP switch (sending creates a new execution_process; the tab itself does
  // not remount thanks to optimisticProcess, but we still want to land at
  // the bottom). Use instant — no smooth animation across an EP transition.
  useEffect(() => {
    scrollToBottom(messagesContainerRef.current, false);
    scrollToBottom(logsContainerRef.current, false);
  }, [process?.id, scrollToBottom]);
  const errorEntry = useMemo(
    () => [...normalizedLogs].reverse().find((entry) => entry.type === "error"),
    [normalizedLogs],
  );
  const taskStatus = String(taskMeta?.status || "").toLowerCase();
  const showTopErrorCard = useMemo(
    () => shouldShowTopErrorCard(errorEntry, taskStatus, taskMeta?.result),
    [errorEntry, taskStatus, taskMeta?.result],
  );
  const canRunInitial = !process && !!taskMeta && (taskStatus === "pending" || taskStatus === "failed");
  const unlockStatus = useMemo(
    () => taskMeta ? getDevelopmentTaskUnlockStatus(taskMeta, allTasks) : { unlocked: true, reason: null },
    [taskMeta, allTasks],
  );
  const blockedReason = !unlockStatus.unlocked ? unlockStatus.reason : null;

  const handleRunInitial = useCallback(() => {
    if (onRunInitial) {
      onRunInitial(executionConfig.executor as "codex" | "claude", executionConfig.provider, executionConfig.model);
    }
  }, [onRunInitial, executionConfig.executor, executionConfig.provider, executionConfig.model]);

  const handleRunAgain = useCallback(() => {
    if (!onRunAgain) return;
    setShowRerunConfirm(true);
  }, [onRunAgain]);

  const handleSend = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim()) return;
    const content = message.trim();
    try {
      onSendMessage(content, runMode);
      setMessage("");
    } catch (err) {
      console.error("Failed to send message:", err);
    }
  }, [message, onSendMessage, runMode]);

  if (isLoadingProcess) {
    return (
      <div className="flex flex-col h-full items-center justify-center gap-4 text-text-muted">
        <Activity size={32} className="animate-spin text-brand" />
        <p className="text-xs font-bold uppercase tracking-widest opacity-60">{t("run.loading")}</p>
      </div>
    );
  }

  if (!process) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-text-muted">
        <MessageSquare size={48} strokeWidth={1} className="mb-4 opacity-10" />
        <p className="text-sm font-medium">{t("run.empty")}</p>
        {canRunInitial && onRunInitial && (
          <div className="mt-6 flex flex-col items-center gap-3">
            {!unlockStatus.unlocked && blockedReason && (
              <p className="text-[10px] font-black uppercase tracking-widest text-warning">{t(blockedReason)}</p>
            )}
            <ExecutionConfigSelector
              value={executionConfig}
              onChange={setExecutionConfig}
              catalog={catalog || null}
            />
            <button
              type="button"
              onClick={handleRunInitial}
              disabled={!unlockStatus.unlocked}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand px-4 py-2 text-xs font-bold uppercase tracking-widest text-background shadow-md transition-all hover:bg-brand/90 active:scale-[0.98] disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Play size={14} className="fill-current" />
              {t("phase.runCurrent")}
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      {/* Header Section */}
      <div className="p-5 border-b border-border-subtle bg-surface/50">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[10px] font-black uppercase tracking-[0.25em] text-text-muted">{t("run.console")}</h2>
          <div className="flex items-center gap-2">
            {taskMeta?.role === "qa" && taskMeta?.status === "done" && qaReportStatus && (
              <QaReportBadge status={qaReportStatus} onView={onViewQaReport} />
            )}
            <AnimatePresence mode="wait">
              <motion.div
                key={process.status}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 1.1 }}
                transition={{ duration: 0.2 }}
              >
                <StatusBadge status={process.status} />
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
        <div className="mb-4">
          <ExecutionConfigSelector
            value={executionConfig}
            onChange={setExecutionConfig}
            catalog={catalog || null}
          />
        </div>
        <div className="flex gap-2.5">
          {process.status?.toLowerCase() === "completed" && (
            <>
              {showTransitionToArchitecture && taskMeta?.phase === "requirements" && (
                <button
                  onClick={onTransitionToArchitecture}
                  disabled={!canTransitionToArchitecture || isTransitioningToArchitecture}
                  className="flex-2 inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-widest rounded-lg bg-brand text-background hover:bg-brand/90 transition-all shadow-md active:scale-[0.98] disabled:opacity-50"
                >
                  {isTransitioningToArchitecture ? t("issue.transition.loading") : t("issue.transition.toArchitecture")}
                </button>
              )}
              {showTransitionToDevelopment && taskMeta?.phase === "architecture" && (
                <button
                  onClick={onTransitionToDevelopment}
                  disabled={!canTransitionToDevelopment || isTransitioningToDevelopment}
                  className="flex-2 inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-widest rounded-lg bg-brand text-background hover:bg-brand/90 transition-all shadow-md active:scale-[0.98] disabled:opacity-50"
                >
                  {isTransitioningToDevelopment ? t("issue.transition.loading") : t("issue.transition.toDevelopment")}
                </button>
              )}
              {showTransitionToTesting && (taskMeta?.phase === "development" || taskMeta?.phase === "testing") && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      onClick={onTransitionToTesting}
                      disabled={!canTransitionToTesting || isTransitioningToTesting}
                      className="flex-2 inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-widest rounded-lg bg-brand text-background hover:bg-brand/90 transition-all shadow-md active:scale-[0.98] disabled:opacity-50"
                    >
                      {isTransitioningToTesting ? "流转中..." : "提交测试"}
                    </button>
                  </TooltipTrigger>
                  {!canTransitionToTesting && !isTransitioningToTesting && (
                    <TooltipContent>请先完成所有开发任务</TooltipContent>
                  )}
                </Tooltip>
              )}
              {taskMeta?.phase === "development" && taskStatus === "done" && !taskMeta?.review_comment && onSubmitForReview && (
                <button
                  onClick={onSubmitForReview}
                  className="flex-2 inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-widest rounded-lg bg-success text-background hover:bg-success/90 transition-all shadow-md active:scale-[0.98]"
                >
                  {t("task.submitForReview")}
                </button>
              )}
              {taskMeta?.phase === "development" && taskStatus !== "done" && taskStatus !== "awaiting_review" && taskStatus !== "rework" && !taskMeta?.review_comment && onSubmitForReview && (
                <div className="flex-2 inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-widest rounded-lg bg-warning/10 text-warning border border-warning/30">
                  <AlertCircle size={14} />
                  <span>任务状态: {taskStatus.toUpperCase()} (需要 DONE 才能提交质检)</span>
                </div>
              )}
            </>
          )}
          <button
            onClick={handleRunAgain}
            className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-widest rounded-lg bg-surface-raised border border-border-subtle hover:bg-surface-hover hover:border-border-strong transition-all active:scale-[0.98]"
          >
            <RotateCcw size={14} />
            {t("run.rerun")}
          </button>
          {onTerminate && (
            <Tooltip>
              <TooltipTrigger
                onClick={onTerminate}
                className="p-2.5 rounded-lg hover:bg-error/10 text-text-muted hover:text-error transition-all active:scale-[0.9] border border-transparent hover:border-error/20"
              >
                <Activity size={14} className="text-error animate-pulse" />
              </TooltipTrigger>
              <TooltipContent side="bottom">Stop Task</TooltipContent>
            </Tooltip>
          )}
          <Tooltip>
            <TooltipTrigger
              onClick={onDelete}
              className="p-2.5 rounded-lg hover:bg-error/10 text-text-muted hover:text-error transition-all active:scale-[0.9] border border-transparent hover:border-error/20"
            >
              <Trash2 size={14} />
            </TooltipTrigger>
            <TooltipContent side="bottom">Delete Session</TooltipContent>
          </Tooltip>
        </div>
        {showTopErrorCard && errorEntry && (
          <div className="mt-4 flex max-h-48 gap-3 rounded-xl border border-error/25 bg-error/10 px-4 py-3 text-error">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <div className="min-w-0 overflow-y-auto pr-1">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]">{errorEntry.label || t("run.error")}</p>
              <p className="mt-1 text-xs leading-relaxed break-words whitespace-pre-wrap text-error/90">{errorEntry.content}</p>
            </div>
          </div>
        )}
        {taskStatus === "failed" && taskMeta?.result && (
          <div className="mt-4 flex max-h-48 gap-3 rounded-xl border border-error/25 bg-error/10 px-4 py-3 text-error">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <div className="min-w-0 overflow-y-auto pr-1">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]">任务执行失败</p>
              <p className="mt-1 text-xs leading-relaxed break-words text-error/90 whitespace-pre-wrap">{taskMeta.result}</p>
            </div>
          </div>
        )}
      </div>
      
      {/* Automated Review Feedback (Prominent) */}
      {(taskMeta?.status === "rework" || taskMeta?.status === "done") && taskMeta?.review_comment && (
        <div className="px-5 pt-4">
          <div className={cn(
            "p-5 rounded-2xl space-y-3 animate-in fade-in slide-in-from-top-2 duration-500",
            taskMeta.status === "rework" ? "bg-error/10 border border-error/20" : "bg-success/10 border border-success/20 shadow-lg shadow-success/5"
          )}>
            <h4 className={cn(
              "text-[10px] font-black uppercase tracking-widest flex items-center gap-2",
              taskMeta.status === "rework" ? "text-error" : "text-success"
            )}>
              {taskMeta.status === "rework" ? <AlertCircle size={12} /> : <Check size={12} />}
              {taskMeta.status === "rework" ? "架构师驳回：需改进" : "架构师评审：通过"}
            </h4>
            <p className="text-xs text-text-muted leading-relaxed whitespace-pre-wrap font-medium">
              {taskMeta.review_comment}
            </p>
            {taskMeta.status === "rework" && (
              <button
                onClick={() => onSendMessage(taskMeta.review_comment!, "refine")}
                className="mt-1 w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-black uppercase tracking-widest rounded-xl bg-error text-background hover:bg-error/90 transition-all shadow-md active:scale-[0.98]"
              >
                <RotateCcw size={13} />
                按建议修订
              </button>
            )}
          </div>
        </div>
      )}

      {/* Main Content Area with Internal Tabs */}
      <div className="flex-1 min-h-0 flex flex-col bg-surface/5">
        <Tabs defaultValue="messages" className="flex-1 flex flex-col min-h-0">
          <div className="px-5 border-b border-border-subtle bg-surface/20">
            <TabsList className="bg-transparent h-12 w-full justify-start gap-6 p-0">
              <TabsTrigger
                value="messages"
                className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:text-brand relative h-full rounded-none border-b-2 border-transparent data-[state=active]:border-brand px-0 text-[10px] font-bold uppercase tracking-[0.15em] transition-all"
              >
                {t("run.communications")}
                <span className="ml-2 text-[9px] opacity-40 font-mono">[{task.length}]</span>
              </TabsTrigger>
              <TabsTrigger
                value="logs"
                className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:text-brand relative h-full rounded-none border-b-2 border-transparent data-[state=active]:border-brand px-0 text-[10px] font-bold uppercase tracking-[0.15em] transition-all"
              >
                {t("run.logs")}
                <span className="ml-2 text-[9px] opacity-40 font-mono">[{normalizedLogs.length}]</span>
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="flex-1 min-h-0 relative">
            <TabsContent ref={messagesContainerRef} value="messages" className="absolute inset-0 m-0 overflow-y-auto p-6 space-y-6 animate-in fade-in duration-300">
              {isLoadingMessages ? (
                <div className="py-20 flex flex-col items-center justify-center gap-4 text-[10px] uppercase font-black tracking-widest text-text-muted opacity-40">
                  <Activity size={24} className="animate-spin text-brand" />
                  <span>{t("run.loadingMessages")}</span>
                </div>
              ) : mergedMessages.length === 0 && !liveStream.pendingAssistant ? (
                <EmptyState
                  icon="message"
                  title={t("run.noMessages")}
                  description="Start a task to see communications"
                  className="py-24"
                />
              ) : (
                <div className="space-y-8">
                  <AnimatePresence initial={false}>
                    {mergedMessages.map((msg) => (
                      <motion.div
                        key={msg.id}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="flex flex-col gap-3"
                      >
                        <div className="flex items-center gap-2.5 px-1">
                          <div className={cn(
                            "size-1.5 rounded-full",
                            msg.role === "assistant" ? "bg-brand shadow-[0_0_8px_rgba(122,157,204,0.6)]" : "bg-text-muted/40"
                          )} />
                          <span className="text-[10px] font-black uppercase tracking-widest text-text-muted">{msg.role}</span>
                        </div>
                        <div className={cn(
                          "p-5 rounded-2xl text-[13.5px] leading-relaxed border font-medium",
                          msg.role === "assistant"
                            ? "bg-brand/5 border-brand/20 text-foreground/90 shadow-sm"
                            : "bg-surface-raised/40 border-border-subtle text-text-secondary"
                        )}>
                          {msg.role === "assistant" ? (
                            <MessageMarkdown content={msg.content || ""} />
                          ) : (
                            <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                          )}
                        </div>
                      </motion.div>
                    ))}
                    {liveStream.pendingAssistant && (
                      <motion.div
                        key="pending-assistant"
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        className="flex flex-col gap-3"
                      >
                        <div className="flex items-center gap-2.5 px-1">
                          <div className="size-1.5 rounded-full bg-brand shadow-[0_0_8px_rgba(122,157,204,0.6)] animate-pulse" />
                          <span className="text-[10px] font-black uppercase tracking-widest text-text-muted">assistant · 输出中</span>
                        </div>
                        <div className="p-5 rounded-2xl text-[13.5px] leading-relaxed border font-medium bg-brand/5 border-brand/20 text-foreground/90 shadow-sm">
                          <MessageMarkdown content={liveStream.pendingAssistant.text || ""} />
                          <motion.span
                            animate={{ opacity: [0, 1, 0] }}
                            transition={{ duration: 0.8, repeat: Infinity }}
                            className="inline-block ml-0.5 -mb-0.5 w-1.5 h-4 bg-brand align-middle"
                          >&nbsp;</motion.span>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )}
            </TabsContent>

            <TabsContent ref={logsContainerRef} value="logs" className="absolute inset-0 m-0 overflow-y-auto p-6 bg-background/40">
              {isLoadingLogs ? (
                <div className="py-20 flex flex-col items-center justify-center gap-4 text-[10px] uppercase font-black tracking-widest text-text-muted opacity-40">
                  <Terminal size={24} className="animate-pulse text-brand" />
                  <span>{t("run.loadingLogs")}</span>
                </div>
              ) : normalizedLogs.length === 0 ? (
                <EmptyState
                  icon="log"
                  title={t("run.noLogs")}
                  description="Logs will appear when the task runs"
                  className="py-24"
                />
              ) : (
                <div className="selection:bg-brand/30 pb-10 space-y-2">
                  <AnimatePresence initial={false}>
                    {normalizedLogs.map((log, i) => (
                      <motion.div
                        key={log.id || i}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.2 }}
                      >
                        {log.type === "tool" ? (
                          <ToolBlock entry={log} />
                        ) : (
                          <div
                            className={cn(
                              "flex gap-4 group px-3 py-2 rounded-xl border transition-colors",
                              log.type === "error"
                                ? "bg-error/10 border-error/20"
                                : log.type === "assistant"
                                  ? "bg-brand/5 border-brand/20"
                                  : log.type === "help"
                                    ? "bg-warning/10 border-warning/20"
                                    : "bg-surface/30 border-transparent hover:bg-surface-hover/50",
                            )}
                          >
                            <span className="shrink-0 text-[10px] font-mono font-bold text-text-muted/30 select-none w-8 text-right group-hover:text-text-muted/60 transition-colors">
                              {i + 1}
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2 mb-1">
                                <span
                                  className={cn(
                                    "text-[9px] font-black uppercase tracking-[0.16em]",
                                    log.type === "error" ? "text-error" : "text-text-muted",
                                  )}
                                >
                                  {log.label}
                                </span>
                              </div>
                              {log.type === "assistant" && log.content ? (
                                <MessageMarkdown content={log.content} />
                              ) : log.content ? (
                                <p className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-text-secondary group-hover:text-foreground transition-colors">
                                  {log.content}
                                </p>
                              ) : null}
                            </div>
                          </div>
                        )}
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              )}
            </TabsContent>
          </div>
        </Tabs>
      </div>

      {/* Input Section */}
      <div className="p-5 border-t border-border-subtle bg-surface/50 space-y-3">
        {/* Run mode chip — chat / refine / rerun */}
        <div className="flex items-center gap-2">
          {([
            { id: "auto", label: "自动", hint: "根据内容自动判别为对话或修订" },
            { id: "chat", label: "对话", hint: "自然语言追问，不修改产物" },
            { id: "refine", label: "修订", hint: "基于现有产物按你的要求改写并保存" },
          ] as { id: RunMode; label: string; hint: string }[]).map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setRunMode(m.id)}
              title={m.hint}
              className={cn(
                "px-3 py-1 text-[10px] font-black uppercase tracking-widest rounded-md border transition-all",
                runMode === m.id
                  ? "bg-brand text-background border-brand"
                  : "bg-surface-raised text-text-muted border-border-subtle hover:border-border-strong",
              )}
            >
              {m.label}
            </button>
          ))}
          <span className="text-[10px] text-text-muted ml-2">
            {runMode === "auto" && "自动模式：按内容判别对话/修订"}
            {runMode === "chat" && "对话模式：不会修改任务产物"}
            {runMode === "refine" && "修订模式：会按指令更新产物文件"}
          </span>
          {runMode === "auto" && lastResolvedMode && (
            <span
              className={cn(
                "ml-auto px-2 py-0.5 rounded-md text-[10px] font-black uppercase tracking-widest border",
                lastResolvedMode === "refine"
                  ? "bg-warning/10 text-warning border-warning/30"
                  : "bg-brand/10 text-brand border-brand/30",
              )}
              title="自动判别结果"
            >
              {lastResolvedMode === "refine" ? "上次：修订" : "上次：对话"}
            </span>
          )}
        </div>
        <form onSubmit={handleSend} className="flex gap-4">
          <div className="flex-1 relative group">
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={runMode === "refine" ? "描述你想要的修改…" : t("run.messagePlaceholder")}
              className="w-full pl-5 pr-14 py-4 text-sm rounded-xl cc-input outline-none shadow-inner font-medium"
            />
            <div className="absolute right-5 top-1/2 -translate-y-1/2 opacity-0 group-focus-within:opacity-100 transition-all scale-90 group-focus-within:scale-100 pointer-events-none">
              <div className="px-2 py-1 rounded-md border border-border-strong text-[9px] font-black text-text-muted uppercase tracking-widest bg-surface-raised">Enter</div>
            </div>
          </div>
          <button
            type="submit"
            disabled={!message.trim()}
            className="px-5 py-4 rounded-xl bg-brand text-background hover:bg-brand/90 transition-all shadow-lg shadow-brand/20 active:scale-95 border border-brand/20 group disabled:opacity-30 disabled:shadow-none flex items-center gap-2"
            title="发送"
          >
            <Send size={20} className="group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
            <span className="text-xs font-bold uppercase tracking-widest">
              {runMode === "refine" ? "修订" : "对话"}
            </span>
          </button>
        </form>
      </div>

      <ConfirmDialog
        open={showRerunConfirm}
        onOpenChange={setShowRerunConfirm}
        title={t("run.rerun")}
        description="重跑会基于原始 prompt 重新生成并覆盖现有产物（如 prd.md / system_design.json）。确认继续？"
        confirmText={t("run.rerun")}
        onConfirm={() => {
          setShowRerunConfirm(false);
          onRunAgain?.(executionConfig.executor as "codex" | "claude", executionConfig.provider, executionConfig.model);
        }}
        variant="warning"
      />
    </div>
  );
}

function QaReportBadge({
  status,
  onView,
}: {
  status: "passed" | "failed" | "blocked" | "needs_follow_up";
  onView?: () => void;
}) {
  const styles: Record<string, { cls: string; label: string }> = {
    passed: { cls: "bg-success/10 text-success border-success/30", label: "测试通过" },
    failed: { cls: "bg-error/10 text-error border-error/30", label: "测试失败" },
    blocked: { cls: "bg-warning/10 text-warning border-warning/30", label: "测试阻塞" },
    needs_follow_up: { cls: "bg-warning/10 text-warning border-warning/30", label: "需要跟进" },
  };
  const entry = styles[status];
  return (
    <button
      type="button"
      onClick={onView}
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-0.5 rounded-md border text-[9px] font-black uppercase tracking-wider transition-opacity",
        entry.cls,
        onView ? "hover:opacity-80 cursor-pointer" : "cursor-default",
      )}
      title={onView ? "查看测试报告" : undefined}
      disabled={!onView}
    >
      {entry.label}
    </button>
  );
}

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const map: Record<string, string> = {
    running: "bg-brand/10 text-brand border-brand/30",
    responding: "bg-brand/10 text-brand border-brand/30",
    completed: "bg-success/10 text-success border-success/30",
    failed: "bg-error/10 text-error border-error/30",
    waiting: "bg-warning/10 text-warning border-warning/30",
    awaiting_review: "bg-warning/10 text-warning border-warning/30 shadow-[0_0_8px_rgba(234,179,8,0.1)]",
    rework: "bg-error/10 text-error border-error/30 shadow-[0_0_8px_rgba(239,68,68,0.1)]",
  };
  const cls = map[s] ?? "bg-surface-input text-text-muted border-border-subtle";
  
  return (
    <div className={cn(
      "flex items-center gap-1.5 px-2.5 py-0.5 rounded-md border text-[9px] font-black uppercase tracking-wider",
      cls
    )}>
      {(s === "running" || s === "responding") && (
        <div className="size-1 rounded-full bg-brand animate-pulse shadow-[0_0_5px_rgba(122,157,204,0.8)]" />
      )}
      {status}
    </div>
  );
}
