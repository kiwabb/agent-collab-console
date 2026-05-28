"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, ChevronRight, Sparkles, Loader2, AlertCircle, WifiOff, XCircle, RotateCcw, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { useExecutionProcessLogStream } from "@/hooks/useExecutionProcessLogStream";
import { normalizeLogs } from "@/lib/codexLogNormalizer";
import { MessageMarkdown } from "./MessageMarkdown";
import { ToolBlock } from "./toolBlocks/ToolBlocks";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import type { NormalizedEntry } from "@/lib/types";

interface AgentLiveTimelineProps {
  executionProcessId: string | null;
  taskStartedAt?: string | null;
  taskCompletedAt?: string | null;
  taskStatus?: string | null;
  reviewComment?: string | null;
  taskResult?: string | null;
  taskRole?: string | null;
  onRerun?: () => Promise<void> | void;
  onStop?: () => Promise<void> | void;
  className?: string;
  emptyHint?: string;
}

const SCROLL_STICKY_PX = 80;

function ThinkingBlock({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  const preview = content.length > 80 ? `${content.slice(0, 80)}…` : content;
  return (
    <div className="rounded-xl border border-amber-500/20 bg-amber-500/5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        {open ? (
          <ChevronDown size={14} className="text-amber-500 shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-amber-500 shrink-0" />
        )}
        <Sparkles size={12} className="text-amber-500 shrink-0 motion-essential animate-neural-pulse" />
        <span className="text-[10px] font-black uppercase tracking-[0.16em] text-amber-500">
          {t("agentLive.thinking")}
        </span>
        {!open ? (
          <span className="truncate text-[11px] text-text-muted italic">{preview}</span>
        ) : null}
      </button>
      {open ? (
        <div className="px-3 pb-3 pl-9">
          <div className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-text-secondary">
            {content}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StreamingAssistantBubble({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="rounded-xl border border-brand/30 bg-brand/5 px-3 py-2">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-[9px] font-black uppercase tracking-[0.16em] text-brand">
          Assistant
        </span>
        <span className="agent-live-cursor motion-essential inline-block h-3 w-px bg-brand" aria-hidden />
      </div>
      <div className="agent-live-streaming">
        <MessageMarkdown content={text} />
      </div>
    </div>
  );
}

function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0s";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

function WorkingIndicator({
  taskStartedAt,
  taskCompletedAt,
  phase,
  elapsedSinceLastMs,
  isFinished,
  isFailed,
  onStop,
  stopBusy,
}: {
  taskStartedAt?: string | null;
  taskCompletedAt?: string | null;
  phase: string;
  elapsedSinceLastMs: number;
  isFinished: boolean;
  isFailed: boolean;
  onStop?: () => Promise<void> | void;
  stopBusy?: boolean;
}) {
  const { t } = useI18n();
  const [nowTick, setNowTick] = useState(() => Date.now());
  useEffect(() => {
    if (isFinished) return;
    const interval = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [isFinished]);

  const startedMs = taskStartedAt ? new Date(taskStartedAt).getTime() : null;
  const completedMs = taskCompletedAt ? new Date(taskCompletedAt).getTime() : null;
  // Once terminal, freeze the duration at the recorded completion time. Falling
  // back to nowTick would measure wall-clock time since start (e.g. opening a
  // task that finished hours ago shows "完成于 91m" instead of its real runtime).
  const endMs = isFinished && completedMs != null ? completedMs : nowTick;
  const elapsedTotalMs = startedMs != null ? endMs - startedMs : 0;

  if (isFailed) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-error/30 bg-error/10 px-3 py-2 text-[11px] text-error">
        <XCircle size={14} />
        <span className="font-mono font-bold">
          {t("agentLive.failedIn").replace("{seconds}", formatElapsed(elapsedTotalMs))}
        </span>
      </div>
    );
  }

  if (isFinished) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-success/20 bg-success/5 px-3 py-2 text-[11px] text-success">
        <span className="inline-block h-2 w-2 rounded-full bg-success" />
        <span className="font-mono">
          {t("agentLive.doneIn").replace("{seconds}", formatElapsed(elapsedTotalMs))}
        </span>
      </div>
    );
  }

  let subtitle: string;
  if (phase === "tool") subtitle = t("agentLive.workingTool");
  else if (phase === "reasoning") subtitle = t("agentLive.workingReasoning");
  else if (phase === "text") subtitle = t("agentLive.workingText");
  else if (elapsedSinceLastMs > 30000) {
    subtitle = t("agentLive.stillAlive").replace(
      "{seconds}",
      formatElapsed(elapsedSinceLastMs),
    );
  } else {
    subtitle = t("agentLive.working");
  }

  return (
    <div className="flex items-center gap-3 rounded-xl border border-brand/20 bg-brand/5 px-3 py-2 text-[11px]">
      <AgentThinkingIndicator phase={phase} label={subtitle} size={14} />
      <div className="ml-auto flex items-center gap-2">
        {startedMs ? (
          <span className="text-text-muted font-mono">{formatElapsed(elapsedTotalMs)}</span>
        ) : null}
        {onStop ? (
          <button
            type="button"
            onClick={() => void onStop()}
            disabled={stopBusy}
            className="inline-flex items-center gap-1 rounded border border-error/40 bg-error/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-error hover:bg-error/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {stopBusy ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <Square size={10} className="fill-error" />
            )}
            {stopBusy ? t("agentLive.stopping") : t("agentLive.stop")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function AgentLiveTimeline({
  executionProcessId,
  taskStartedAt,
  taskCompletedAt,
  taskStatus,
  reviewComment,
  taskResult,
  taskRole,
  onRerun,
  onStop,
  className,
  emptyHint,
}: AgentLiveTimelineProps) {
  const [rerunBusy, setRerunBusy] = useState(false);
  const handleRerun = async () => {
    if (!onRerun || rerunBusy) return;
    setRerunBusy(true);
    try {
      await onRerun();
    } finally {
      setRerunBusy(false);
    }
  };
  const [stopBusy, setStopBusy] = useState(false);
  const handleStop = async () => {
    if (!onStop || stopBusy) return;
    setStopBusy(true);
    try {
      await onStop();
    } finally {
      setStopBusy(false);
    }
  };
  const { t } = useI18n();
  const { logs, streamingAssistant, heartbeat, finished, disconnected, error } =
    useExecutionProcessLogStream(executionProcessId);
  const entries = useMemo<NormalizedEntry[]>(() => normalizeLogs(logs), [logs]);

  const isFailed = useMemo(() => {
    const status = String(taskStatus || "").toLowerCase();
    return status === "failed" || status === "killed";
  }, [taskStatus]);

  const isTerminal = useMemo(() => {
    const status = String(taskStatus || "").toLowerCase();
    return (
      finished ||
      status === "done" ||
      status === "completed" ||
      status === "failed" ||
      status === "killed"
    );
  }, [finished, taskStatus]);

  // When the task is terminal, finalize any tool entries still showing "running".
  // The last tool_result event is often lost when the WS closes before it arrives.
  const displayEntries = useMemo<NormalizedEntry[]>(() => {
    if (!isTerminal) return entries;
    return entries.map((entry) => {
      if (entry.type === "tool" && entry.status === "running") {
        return { ...entry, status: isFailed ? ("failed" as const) : ("success" as const) };
      }
      return entry;
    });
  }, [entries, isTerminal, isFailed]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const autoStickRef = useRef(true);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    if (!autoStickRef.current) return;
    node.scrollTop = node.scrollHeight;
  }, [displayEntries.length, streamingAssistant?.text, heartbeat?.receivedAt]);

  const onScroll = () => {
    const node = scrollRef.current;
    if (!node) return;
    const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    autoStickRef.current = distanceFromBottom <= SCROLL_STICKY_PX;
  };

  const showClarifyBanner =
    String(taskStatus || "").toLowerCase() === "awaiting_review" &&
    typeof reviewComment === "string" &&
    reviewComment.trim().startsWith("[CLARIFY]");

  const failureReason = useMemo(() => {
    if (!isFailed) return null;
    const rc = (reviewComment || "").trim();
    if (rc) return rc;
    const result = (taskResult || "").trim();
    if (result) {
      // Try to parse JSON; if it's a structured QA report, show key fields. Else
      // return the raw text (truncated).
      try {
        const parsed = JSON.parse(result);
        if (parsed && typeof parsed === "object") {
          const bugs = Array.isArray(parsed.bugs_found) ? parsed.bugs_found.join("\n• ") : "";
          const final = typeof parsed.final_recommendation === "string" ? parsed.final_recommendation : "";
          const status = typeof parsed.status === "string" ? parsed.status : "";
          const parts: string[] = [];
          if (status) parts.push(`status: ${status}`);
          if (bugs) parts.push(`bugs:\n• ${bugs}`);
          if (final) parts.push(`recommendation: ${final}`);
          if (parts.length > 0) return parts.join("\n\n");
        }
      } catch {
        // fall through
      }
      return result.length > 800 ? result.slice(0, 800) + "…" : result;
    }
    return null;
  }, [isFailed, reviewComment, taskResult]);

  const isEmpty = displayEntries.length === 0 && !streamingAssistant?.text && !heartbeat;

  return (
    <div className={cn("flex flex-col h-full min-h-0", className)}>
      {isFailed ? (
        <div className="flex items-start gap-2 rounded-xl border border-error/40 bg-error/10 px-3 py-2 mb-2 text-[12px]">
          <XCircle size={16} className="mt-0.5 text-error shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <div className="font-bold text-error flex-1 min-w-0">
                {t("agentLive.taskFailedTitle").replace("{role}", (taskRole || t("agentLive.thisTask")).toUpperCase())}
              </div>
              {onRerun ? (
                <button
                  type="button"
                  onClick={() => void handleRerun()}
                  disabled={rerunBusy}
                  className="shrink-0 inline-flex items-center gap-1 rounded border border-error/40 bg-error/15 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-error hover:bg-error/25 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {rerunBusy ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : (
                    <RotateCcw size={11} />
                  )}
                  {rerunBusy ? t("agentLive.rerunning") : t("agentLive.rerun")}
                </button>
              ) : null}
            </div>
            {failureReason ? (
              <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-text-secondary mt-1">
                {failureReason}
              </pre>
            ) : (
              <div className="text-text-secondary">{t("agentLive.taskFailedHint")}</div>
            )}
          </div>
        </div>
      ) : null}

      {showClarifyBanner ? (
        <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 mb-2 text-[12px]">
          <AlertCircle size={14} className="mt-0.5 text-warning shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="font-bold text-warning mb-0.5">{t("agentLive.awaitingAnswer")}</div>
            <div className="text-text-secondary whitespace-pre-wrap break-words">
              {reviewComment}
            </div>
          </div>
        </div>
      ) : null}

      {disconnected && !isTerminal ? (
        <div className="flex items-center gap-2 rounded-xl border border-error/30 bg-error/10 px-3 py-2 mb-2 text-[11px] text-error">
          <WifiOff size={12} />
          <span>{t("agentLive.disconnected")}</span>
        </div>
      ) : null}

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 min-h-0 overflow-y-auto space-y-2 pb-4 pr-1.5"
      >
        {isEmpty ? (
          <div className="py-12 text-center text-[12px] text-text-muted">
            {executionProcessId ? t("agentLive.waitingForOutput") : emptyHint || t("agentLive.noActiveAgent")}
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {displayEntries.map((entry, idx) => (
              <motion.div
                key={entry.id || idx}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.15 }}
              >
                {entry.type === "tool" ? (
                  <ToolBlock entry={entry} />
                ) : entry.type === "thinking" ? (
                  <ThinkingBlock content={entry.content || ""} />
                ) : (
                  <div
                    className={cn(
                      "flex gap-3 px-3 py-2 rounded-xl border",
                      entry.type === "error"
                        ? "bg-error/10 border-error/20"
                        : entry.type === "assistant"
                          ? "bg-brand/5 border-brand/20"
                          : entry.type === "help"
                            ? "bg-warning/10 border-warning/20"
                            : "bg-surface/30 border-transparent",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="mb-1">
                        <span
                          className={cn(
                            "text-[9px] font-black uppercase tracking-[0.16em]",
                            entry.type === "error" ? "text-error" : "text-text-muted",
                          )}
                        >
                          {entry.label}
                        </span>
                      </div>
                      {entry.type === "assistant" && entry.content ? (
                        <MessageMarkdown content={entry.content} />
                      ) : entry.content ? (
                        <p className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-text-secondary">
                          {entry.content}
                        </p>
                      ) : null}
                    </div>
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
        )}

        {streamingAssistant?.text ? (
          <StreamingAssistantBubble text={streamingAssistant.text} />
        ) : null}

        {executionProcessId ? (
          <WorkingIndicator
            taskStartedAt={taskStartedAt}
            taskCompletedAt={taskCompletedAt}
            phase={heartbeat?.phase || "idle"}
            elapsedSinceLastMs={heartbeat?.elapsedSinceLastMs ?? 0}
            isFinished={isTerminal}
            isFailed={isFailed}
            onStop={!isTerminal ? onStop && handleStop : undefined}
            stopBusy={stopBusy}
          />
        ) : null}
      </div>

      {error ? (
        <div className="mt-2 text-[10px] text-error">{error}</div>
      ) : null}
    </div>
  );
}
