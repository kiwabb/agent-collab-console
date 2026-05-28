"use client";

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Circle, HelpCircle, Loader2, Pause, PauseCircle, Play, SendHorizontal, XCircle } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  getConductorLog,
  getConductorPhaseEstimates,
  getConductorStateLog,
  getConductorState,
  getConductorTurns,
  pauseConductor,
  resumeConductor,
  sendConductorMessage,
  type ConductorDecision,
  type ConductorPhaseEstimate,
  type ConductorStateLogEntry,
  type ConductorStatePayload,
  type ConductorTurn,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { HistoryEntry } from "@/features/agents/dock/agentBus";
import { PERSONAS } from "@/features/agents/dock/personas";
import type { BusConductorStateViolationEvent, BusConductorStatusEvent, BusConductorTurnDeltaEvent, BusConductorTurnEvent } from "@/contexts/ExecutionProcessesContext";
import { useExecutionProcessesContext } from "@/contexts/ExecutionProcessesContext";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  issueId: string;
  open: boolean;
  liveHistory: HistoryEntry[];
  onClose: () => void;
}

type TabId = "thread" | "log" | "turns";
type StreamingBufferMap = Record<string, { turnIndex: number; contentBlockIndex: number; kind: "text" | "tool_input_json"; chunk: string }>;
type TimelineNode = {
  key: string;
  phase: string;
  detail: string | null;
  startedAt: string | null;
  endedAt: string | null;
  durationMs: number | null;
  isCurrent: boolean;
  isLegal: boolean;
  isPaused: boolean;
  isFailed: boolean;
};

function getThreadActionStyles(t: (key: string) => string): Record<string, { label: string; cls: string }> {
  return {
    proceed: { label: t("conductor.action.proceed"), cls: "bg-surface-raised text-text-secondary border-border-subtle" },
    note: { label: t("conductor.action.note"), cls: "bg-info/10 text-info border-info/30" },
    escalate: { label: t("conductor.action.escalate"), cls: "bg-error/10 text-error border-error/30" },
    dispatch_next: { label: t("conductor.action.dispatchNext"), cls: "bg-brand/10 text-brand border-brand/30" },
    inject_context: { label: t("conductor.action.injectContext"), cls: "bg-warning/10 text-warning border-warning/30" },
    spawn_specialist: { label: t("conductor.action.spawnSpecialist"), cls: "bg-success/10 text-success border-success/30" },
    spawn_custom: { label: t("conductor.action.spawnCustom"), cls: "bg-success/10 text-success border-success/30" },
  };
}

function getActionStyles(t: (key: string) => string): Record<ConductorDecision["action"], { label: string; cls: string }> {
  return {
    proceed: { label: t("conductor.action.proceed"), cls: "bg-surface-raised text-text-secondary border-border-subtle" },
    note: { label: t("conductor.action.note"), cls: "bg-info/10 text-info border-info/30" },
    escalate: { label: t("conductor.action.escalate"), cls: "bg-error/10 text-error border-error/30" },
    reroute: { label: t("conductor.action.reroute"), cls: "bg-brand/10 text-brand border-brand/30" },
    insert_node: { label: t("conductor.action.insertNode"), cls: "bg-success/10 text-success border-success/30" },
    request_clarification: { label: t("conductor.action.clarify"), cls: "bg-warning/10 text-warning border-warning/30" },
  };
}

function getTurnStyles(t: (key: string) => string): Record<ConductorTurn["kind"], { label: string; cls: string }> {
  return {
    llm_request: { label: t("conductor.turn.llm"), cls: "bg-brand/10 text-brand border-brand/30" },
    llm_response: { label: t("conductor.turn.response"), cls: "bg-brand/5 text-brand border-brand/20" },
    tool_use: { label: t("conductor.turn.tool"), cls: "bg-warning/10 text-warning border-warning/30" },
    tool_result: { label: t("conductor.turn.result"), cls: "bg-success/10 text-success border-success/30" },
    user_message: { label: t("conductor.turn.you"), cls: "bg-info/10 text-info border-info/30" },
    error: { label: t("conductor.turn.error"), cls: "bg-error/10 text-error border-error/30" },
    finalize: { label: t("conductor.turn.done"), cls: "bg-surface-raised text-text-secondary border-border-subtle" },
  };
}

const STATUS_STYLES: Record<string, string> = {
  running: "bg-brand/10 text-brand border-brand/30",
  paused: "bg-warning/10 text-warning border-warning/30",
  failed: "bg-error/10 text-error border-error/30",
  done: "bg-success/10 text-success border-success/30",
  completed: "bg-success/10 text-success border-success/30",
  max_turns: "bg-surface-raised text-text-secondary border-border-subtle",
};

function relTime(iso: string | null): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 1000) return "just now";
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  return `${Math.floor(ms / 3_600_000)}h ago`;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function buildTimelineNodes(
  entries: ConductorStateLogEntry[],
  currentPhase: string | null,
  currentDetail: string | null,
  nowMs: number,
): TimelineNode[] {
  const ascending = [...entries].sort((a, b) => {
    const aMs = a.transition_at ? new Date(a.transition_at).getTime() : 0;
    const bMs = b.transition_at ? new Date(b.transition_at).getTime() : 0;
    return aMs - bMs;
  });
  const nodes: TimelineNode[] = [];
  for (let index = 0; index < ascending.length; index += 1) {
    const entry = ascending[index];
    const next = ascending[index + 1];
    const isResumeEcho = index > 0
      && ascending[index - 1]?.to_phase === "paused"
      && entry.from_phase === "paused"
      && entry.to_phase === ascending[index - 1]?.from_phase;
    if (isResumeEcho) continue;
    const startedAtMs = entry.transition_at ? new Date(entry.transition_at).getTime() : null;
    const endedAtMs = next?.transition_at ? new Date(next.transition_at).getTime() : null;
    const isCurrent = !next && currentPhase === entry.to_phase;
    nodes.push({
      key: entry.id,
      phase: entry.to_phase,
      detail: isCurrent ? currentDetail : (entry.to_detail ?? null),
      startedAt: entry.transition_at,
      endedAt: next?.transition_at ?? null,
      durationMs: endedAtMs != null && startedAtMs != null
        ? Math.max(1, endedAtMs - startedAtMs)
        : isCurrent && startedAtMs != null
          ? Math.max(0, nowMs - startedAtMs)
          : entry.duration_ms,
      isCurrent,
      isLegal: entry.is_legal,
      isPaused: entry.to_phase === "paused",
      isFailed: entry.to_phase === "failed",
    });
  }
  if (nodes.length === 0 && currentPhase) {
    nodes.push({
      key: `live-${currentPhase}`,
      phase: currentPhase,
      detail: currentDetail,
      startedAt: null,
      endedAt: null,
      durationMs: null,
      isCurrent: true,
      isLegal: true,
      isPaused: currentPhase === "paused",
      isFailed: currentPhase === "failed",
    });
  }
  return nodes;
}

function isConductorTurnEvent(evt: unknown): evt is BusConductorTurnEvent {
  if (!evt || typeof evt !== "object") return false;
  const record = evt as Record<string, unknown>;
  return (
    record.type === "conductor_turn" &&
    typeof record.id === "string" &&
    typeof record.issue_id === "string" &&
    typeof record.conductor_task_id === "string" &&
    typeof record.turn_index === "number" &&
    typeof record.sub_index === "number" &&
    typeof record.kind === "string" &&
    !!record.payload &&
    typeof record.payload === "object"
  );
}

function isConductorStatusEvent(evt: unknown): evt is BusConductorStatusEvent {
  if (!evt || typeof evt !== "object") return false;
  const record = evt as Record<string, unknown>;
  return (
    record.type === "conductor_status" &&
    typeof record.issue_id === "string" &&
    typeof record.conductor_task_id === "string" &&
    typeof record.status === "string"
  );
}

function isConductorTurnDeltaEvent(evt: unknown): evt is BusConductorTurnDeltaEvent {
  if (!evt || typeof evt !== "object") return false;
  const record = evt as Record<string, unknown>;
  return (
    record.type === "conductor_turn_delta" &&
    typeof record.issue_id === "string" &&
    typeof record.conductor_task_id === "string" &&
    typeof record.turn_index === "number" &&
    typeof record.sub_index === "number" &&
    typeof record.kind === "string" &&
    typeof record.chunk === "string" &&
    typeof record.content_block_index === "number"
  );
}

function isConductorStateViolationEvent(evt: unknown): evt is BusConductorStateViolationEvent {
  if (!evt || typeof evt !== "object") return false;
  const record = evt as Record<string, unknown>;
  return (
    record.type === "conductor_state_violation" &&
    typeof record.issue_id === "string" &&
    typeof record.conductor_task_id === "string" &&
    typeof record.to_phase === "string"
  );
}

export function ConductorLogPanel({ issueId, open, liveHistory, onClose }: Props) {
  const [decisions, setDecisions] = useState<ConductorDecision[]>([]);
  const [turns, setTurns] = useState<ConductorTurn[]>([]);
  const [conductorState, setConductorState] = useState<ConductorStatePayload | null>(null);
  const [stateLog, setStateLog] = useState<ConductorStateLogEntry[]>([]);
  const [phaseEstimates, setPhaseEstimates] = useState<Record<string, ConductorPhaseEstimate>>({});
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>("thread");
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [statusBusy, setStatusBusy] = useState<"pause" | "resume" | null>(null);
  const [streamingBuffers, setStreamingBuffers] = useState<StreamingBufferMap>({});
  const [nowMs, setNowMs] = useState(() => Date.now());
  const persona = PERSONAS["conductor"];
  const { t } = useI18n();
  const { resumeGapCount } = useExecutionProcessesContext();
  const translatedName = t(persona.nameKey);
  const translatedBlurb = t(persona.blurbKey);

  const THREAD_ACTION_STYLES = getThreadActionStyles(t);
  const ACTION_STYLES = getActionStyles(t);
  const TURN_STYLES = getTurnStyles(t);

  const reload = useCallback(() => {
    if (!open) return;
    setLoading(true);
    Promise.all([
      getConductorLog(issueId).then((d) => setDecisions([...d].reverse())).catch(() => setDecisions([])),
      getConductorState(issueId).then(setConductorState).catch(() => setConductorState(null)),
      getConductorTurns(issueId).then(setTurns).catch(() => setTurns([])),
      getConductorStateLog(issueId, { limit: 200 }).then((entries) => setStateLog(entries)).catch(() => setStateLog([])),
      getConductorPhaseEstimates(issueId).then(setPhaseEstimates).catch(() => setPhaseEstimates({})),
    ]).finally(() => setLoading(false));
  }, [issueId, open]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (!open || resumeGapCount === 0) return;
    reload();
  }, [open, reload, resumeGapCount]);

  useEffect(() => {
    if (!open) return undefined;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [open]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_decision"),
    ),
    onEvent: reload,
    throttleMs: 800,
    enabled: open,
  });

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_turn"),
    ),
    onEvent: (evt) => {
      if (!isConductorTurnEvent(evt)) return;
      const turn: ConductorTurn = {
        id: evt.id,
        conductor_task_id: evt.conductor_task_id,
        issue_id: evt.issue_id,
        turn_index: evt.turn_index,
        sub_index: evt.sub_index,
        kind: evt.kind,
        payload: evt.payload,
        created_at: evt.created_at,
      };
      setTurns((prev) => {
        if (prev.some((entry) => entry.id === turn.id)) return prev;
        return [...prev, turn];
      });
      if (turn.kind === "llm_response") {
        setStreamingBuffers((prev) => {
          const next: StreamingBufferMap = {};
          const prefix = `${turn.turn_index}:`;
          for (const [key, value] of Object.entries(prev)) {
            if (!key.startsWith(prefix)) next[key] = value;
          }
          return next;
        });
      }
    },
    enabled: open,
  });

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_turn_delta"),
    ),
    onEvent: (evt) => {
      if (!isConductorTurnDeltaEvent(evt)) return;
      setStreamingBuffers((prev) => {
        const key = `${evt.turn_index}:${evt.content_block_index}:${evt.kind}`;
        const existing = prev[key];
        return {
          ...prev,
          [key]: {
            turnIndex: evt.turn_index,
            contentBlockIndex: evt.content_block_index,
            kind: evt.kind,
            chunk: `${existing?.chunk ?? ""}${evt.chunk}`,
          },
        };
      });
    },
    enabled: open,
  });

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_failed"),
    ),
    onEvent: reload,
    throttleMs: 300,
    enabled: open,
  });

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_status"),
    ),
    onEvent: (evt) => {
      if (!isConductorStatusEvent(evt)) return;
      setConductorState((prev) => ({
        issue_id: prev?.issue_id ?? issueId,
        running_thread: prev?.running_thread ?? [],
        pending_dispatches: prev?.pending_dispatches ?? [],
        scratchpad: prev?.scratchpad ?? "",
        decision_count: prev?.decision_count ?? 0,
        updated_at: evt.updated_at ?? prev?.updated_at ?? null,
        conductor_task_id: evt.conductor_task_id,
        conductor_status: evt.status,
        phase: evt.phase ?? prev?.phase ?? null,
        detail: evt.detail ?? prev?.detail ?? null,
      }));
      if (!evt.phase || !evt.updated_at) return;
      const nextPhase = evt.phase;
      const updatedAt = evt.updated_at;
      setStateLog((prev) => {
        const existing = prev[0];
        if (
          existing &&
          existing.transition_at === updatedAt &&
          existing.to_phase === nextPhase &&
          (existing.to_detail ?? null) === (evt.detail ?? null)
        ) {
          return prev;
        }
        const nextEntry: ConductorStateLogEntry = {
          id: `live-${evt.conductor_task_id}-${updatedAt}`,
          issue_id: issueId,
          from_phase: existing?.to_phase ?? null,
          to_phase: nextPhase,
          from_detail: existing?.to_detail ?? null,
          to_detail: evt.detail ?? null,
          transition_at: updatedAt,
          duration_ms: existing?.transition_at
            ? Math.max(1, new Date(updatedAt).getTime() - new Date(existing.transition_at).getTime())
            : null,
          is_legal: true,
        };
        return [nextEntry, ...prev];
      });
    },
    enabled: open,
  });

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("conductor_state_violation"),
    ),
    onEvent: (evt) => {
      if (!isConductorStateViolationEvent(evt)) return;
      setStateLog((prev) => prev.map((entry, index) => (
        index === 0 && entry.to_phase === evt.to_phase
          ? { ...entry, is_legal: false }
          : entry
      )));
    },
    enabled: open,
  });

  const thread = conductorState?.running_thread ?? [];
  const pending = conductorState?.pending_dispatches ?? [];
  const conductorStatus = conductorState?.conductor_status ?? "idle";
  const conductorPhase = conductorState?.phase ?? null;
  const phaseStartedAt = conductorState?.updated_at ? new Date(conductorState.updated_at).getTime() : null;
  const phaseElapsedMs = phaseStartedAt ? Math.max(0, nowMs - phaseStartedAt) : 0;
  const phaseElapsedSeconds = Math.floor(phaseElapsedMs / 1000);
  const conductorDetail = conductorPhase === "awaiting_subagent" && conductorState?.detail
    ? `${conductorState.detail} (${phaseElapsedSeconds}s)`
    : (conductorState?.detail ?? null);
  const translatedStatus = t(`conductor.status.${conductorStatus}` as any) ?? conductorStatus;
  const isPaused = conductorStatus === "paused";
  const hasActiveLoop = Boolean(conductorState?.conductor_task_id) && !["done", "completed", "failed", "max_turns"].includes(conductorStatus);
  const statusCls = STATUS_STYLES[conductorStatus] ?? "bg-surface-raised text-text-secondary border-border-subtle";
  const streamingPreview = Object.values(streamingBuffers)
    .sort((a, b) => a.turnIndex - b.turnIndex || a.contentBlockIndex - b.contentBlockIndex || a.kind.localeCompare(b.kind))
    .map((entry) => entry.chunk)
    .join("");
  const stuck = conductorPhase === "awaiting_subagent" && phaseElapsedSeconds > 30;
  const timelineNodes = buildTimelineNodes(stateLog, conductorPhase, conductorState?.detail ?? null, nowMs);
  const currentEstimate = conductorPhase ? phaseEstimates[conductorPhase] : undefined;
  const estimateLabel = currentEstimate?.p50_ms != null
    ? `${currentEstimate.n_samples < 5 ? "~" : ""}${formatDuration(currentEstimate.p50_ms)}`
    : "—";
  const estimateTone = currentEstimate?.n_samples && currentEstimate.n_samples < 5
    ? "text-text-muted"
    : "text-text-secondary";
  const isSlowerThanP95 = currentEstimate?.p95_ms != null && phaseElapsedMs > currentEstimate.p95_ms;
  const progressMax = currentEstimate?.p50_ms ?? 1;

  const handleSend = useCallback(async () => {
    const message = composer.trim();
    if (!message) return;
    setSending(true);
    try {
      const result = await sendConductorMessage(issueId, message);
      setComposer("");
      setConductorState((prev) => prev ? {
        ...prev,
        conductor_task_id: result.conductor_task_id,
        conductor_status: result.status,
        phase: prev.phase ?? "awaiting_llm",
      } : prev);
    } finally {
      setSending(false);
    }
  }, [composer, issueId]);

  const handlePauseResume = useCallback(async () => {
    if (!conductorState?.conductor_task_id) return;
    const nextMode = isPaused ? "resume" : "pause";
    setStatusBusy(nextMode);
    try {
      const result = isPaused ? await resumeConductor(issueId) : await pauseConductor(issueId);
      setConductorState((prev) => prev ? {
        ...prev,
        conductor_task_id: result.conductor_task_id,
        conductor_status: result.status,
        phase: isPaused ? "awaiting_llm" : "paused",
      } : prev);
    } finally {
      setStatusBusy(null);
    }
  }, [conductorState?.conductor_task_id, isPaused, issueId]);

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[480px] sm:w-[560px] flex flex-col gap-0 p-0">
        <SheetHeader className="px-5 pt-4 pb-4 shrink-0 border-b border-border-subtle bg-surface/80 backdrop-blur-sm">
          <div className="flex items-start gap-3">
            <SheetTitle className="flex items-center gap-3 text-lg">
              <span
                className="w-10 h-10 rounded-2xl flex items-center justify-center text-2xl border"
                style={{ borderColor: persona.color, background: `${persona.color}11` }}
                aria-hidden
              >
                {persona.emoji}
              </span>
              {translatedName}
            </SheetTitle>
            <span className={cn("ml-auto inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider", statusCls)}>
              {translatedStatus}
            </span>
          </div>
          <SheetDescription className="text-xs text-text-muted">
            {translatedBlurb}
          </SheetDescription>
          {(conductorPhase || conductorDetail || streamingPreview) && (
            <div
              className={cn(
                "mt-3 rounded-2xl border px-3 py-3 text-xs",
                stuck ? "border-warning/50 bg-warning/10 text-warning" : "border-border-subtle bg-surface-raised/80 text-text-secondary",
              )}
            >
              {conductorPhase && (
                <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em]">
                  {!isPaused && <AgentThinkingIndicator phase={conductorPhase} size={12} />}
                  {conductorPhase}
                </div>
              )}
              {conductorDetail && (
                <div className="mt-1 leading-relaxed">{conductorDetail}</div>
              )}
              {streamingPreview && (
                <pre className="mt-2 whitespace-pre-wrap break-words text-[11px] text-text-primary">
                  {streamingPreview}
                </pre>
              )}
            </div>
          )}
          {timelineNodes.length > 0 && (
            <div className="mt-3 rounded-2xl border border-border-subtle bg-background/60 px-3 py-3">
              <div className="mb-2 flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-text-muted">
                <span>{t("conductor.panel.timeline")}</span>
                <span>{timelineNodes.length}</span>
              </div>
              <div className="overflow-x-auto pb-1">
                <div className="flex min-w-max items-start gap-2.5">
                  <AnimatePresence initial={false}>
                    {timelineNodes.map((node) => {
                      const Icon = node.isFailed ? XCircle : node.isPaused ? PauseCircle : Circle;
                      const nodeTone = node.isFailed
                        ? "border-error/40 bg-error/10 text-error"
                        : !node.isLegal
                          ? "border-warning/40 bg-warning/10 text-warning"
                          : node.isCurrent
                            ? "border-brand/40 bg-brand/10 text-brand"
                            : "border-border-subtle bg-surface-raised text-text-secondary";
                      return (
                        <motion.div
                          key={node.key}
                          layout
                          initial={{ opacity: 0, scale: 0.85, y: 8 }}
                          animate={{ opacity: 1, scale: 1, y: 0 }}
                          exit={{ opacity: 0, scale: 0.85, y: 8 }}
                          transition={{ type: "spring", stiffness: 320, damping: 24, mass: 0.7 }}
                          className="relative flex items-start gap-3"
                        >
                          <div className={cn("flex w-[154px] shrink-0 flex-col rounded-2xl border px-3 py-2.5", nodeTone)}>
                            <div className="flex items-center gap-2">
                              <Icon className={cn("h-3.5 w-3.5", node.isCurrent && !node.isPaused && "motion-essential animate-neural-pulse")} />
                              <span className="font-mono text-[11px] uppercase tracking-wider">{node.phase}</span>
                            </div>
                            <div className="mt-1 text-[10px] leading-relaxed text-text-muted">
                              {node.detail || "—"}
                            </div>
                            <div className="mt-2 text-[10px] font-semibold">
                              {formatDuration(node.durationMs)}
                            </div>
                            {node.isPaused && (
                              <div className="mt-1 flex items-center gap-1 text-[10px] text-warning">
                                <PauseCircle className="h-3 w-3" />
                                <span>{t("conductor.panel.pauseMerged")}</span>
                              </div>
                            )}
                            {!node.isLegal && (
                              <div className="mt-1 flex items-center gap-1 text-[10px] text-warning">
                                <AlertTriangle className="h-3 w-3" />
                                <span>{t("conductor.panel.illegalTransition")}</span>
                              </div>
                            )}
                          </div>
                          <div className="mt-6 h-px w-6 shrink-0 bg-border-subtle last:hidden" />
                        </motion.div>
                      );
                    })}
                  </AnimatePresence>
                </div>
              </div>
            </div>
          )}
          {conductorPhase && (
            <div className="mt-3 rounded-2xl border border-border-subtle bg-surface-raised px-3 py-3 text-xs">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-text-muted">
                    {t("conductor.panel.estimate")}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-sm text-text-secondary">
                    <span>{t("conductor.panel.elapsedEstimate", { elapsed: formatDuration(phaseElapsedMs), estimate: estimateLabel })}</span>
                    {currentEstimate?.n_samples != null && currentEstimate.n_samples < 5 && (
                      <Tooltip>
                        <TooltipTrigger>
                          <HelpCircle className={cn("h-3.5 w-3.5", estimateTone)} />
                        </TooltipTrigger>
                        <TooltipContent side="bottom">
                          {t("conductor.panel.lowConfidence", { count: currentEstimate.n_samples })}
                        </TooltipContent>
                      </Tooltip>
                    )}
                  </div>
                </div>
                <div className={cn("text-[10px] font-semibold", estimateTone)}>
                  N={currentEstimate?.n_samples ?? 0}
                </div>
              </div>
              <div className="mt-3 flex items-center gap-3">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-input">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all duration-300 ease-out",
                      isSlowerThanP95 ? "bg-warning" : "bg-brand",
                    )}
                    style={{ width: `${Math.min(100, Math.max(0, (phaseElapsedMs / progressMax) * 100))}%` }}
                  />
                </div>
                <span className="min-w-[3rem] text-right text-[10px] font-bold text-text-muted">
                  {`${Math.min(999, Math.round((phaseElapsedMs / progressMax) * 100))}%`}
                </span>
              </div>
              {isSlowerThanP95 && (
                <div className="mt-2 text-[10px] font-semibold text-warning">
                  {t("conductor.panel.slowerThanP95")}
                </div>
              )}
            </div>
          )}
          <div className="flex items-center justify-end gap-2 pt-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!hasActiveLoop || !!statusBusy}
              onClick={() => void handlePauseResume()}
            >
              {statusBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : isPaused ? (
                <Play className="mr-1.5 h-3.5 w-3.5" />
              ) : (
                <Pause className="mr-1.5 h-3.5 w-3.5" />
              )}
              {isPaused ? t("conductor.panel.resume") : t("conductor.panel.pause")}
            </Button>
          </div>
        </SheetHeader>

        {liveHistory.length > 0 && (
          <div className="px-5 py-3 border-b border-border-subtle shrink-0">
            <div className="text-[10px] font-black uppercase tracking-widest text-text-muted mb-2">
              {t("conductor.panel.liveEvents", { count: liveHistory.length })}
            </div>
            <div className="flex flex-col gap-1 max-h-[100px] overflow-y-auto">
              {[...liveHistory].reverse().map((e, i) => (
                <div key={i} className="flex items-baseline gap-2 text-xs">
                  <span className="text-text-secondary shrink-0">{e.text}</span>
                  {e.detail && (
                    <span className="text-text-faint font-mono truncate">{e.detail}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex border-b border-border-subtle shrink-0 px-2 pt-2 gap-1 bg-surface/70 backdrop-blur-sm">
          {(["thread", "log", "turns"] as TabId[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-4 py-2 text-[11px] font-black uppercase tracking-widest rounded-t-xl transition-colors",
                activeTab === tab
                  ? "bg-surface-raised text-brand"
                  : "text-text-muted hover:text-text-secondary",
              )}
              style={activeTab === tab ? { borderBottomColor: persona.color } : {}}
            >
              {tab === "thread"
                ? t("conductor.panel.threadTab", { count: thread.length })
                : tab === "log"
                  ? t("conductor.panel.logTab", { count: decisions.length })
                  : t("conductor.panel.turnsTab", { count: turns.length })}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-auto px-5 py-4">
          {loading && (
            <div className="text-sm text-text-muted py-6 text-center">{t("conductor.panel.loading")}</div>
          )}

          {!loading && activeTab === "thread" && (
            <>
              {pending.length > 0 && (
                <div className="mb-4 rounded-2xl border border-brand/20 bg-brand/5 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-brand mb-2">
                    {pending.length > 1 ? t("conductor.panel.pendingDispatch", { count: pending.length }) : t("conductor.panel.pendingDispatchSingular")}
                  </div>
                  {pending.map((p, i) => {
                    const style = THREAD_ACTION_STYLES[p.action] ?? THREAD_ACTION_STYLES.proceed;
                    return (
                      <div key={i} className="flex items-start gap-2 text-xs mt-1">
                        <span className={cn("rounded border px-1.5 py-0.5 text-[9px] font-black uppercase shrink-0", style.cls)}>
                          {style.label}
                        </span>
                        {p.target_node_key && (
                          <span className="font-mono text-text-secondary">→ {p.target_node_key}</span>
                        )}
                        {p.reason && (
                          <span className="text-text-muted truncate">{p.reason}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {conductorState?.scratchpad && (
                <details className="mb-4">
                  <summary className="text-[10px] font-black uppercase tracking-widest text-text-muted cursor-pointer hover:text-text-secondary">
                    {t("conductor.panel.scratchpad")}
                  </summary>
                  <p className="mt-2 text-xs text-text-secondary bg-surface-raised rounded-xl px-3 py-2 leading-relaxed whitespace-pre-wrap">
                    {conductorState.scratchpad}
                  </p>
                </details>
              )}

              {thread.length === 0 ? (
                <div className="text-sm text-text-muted py-6 text-center">
                  {t("conductor.panel.noThreadYet")}
                </div>
              ) : (
                <ol className="relative border-l border-border-subtle ml-2 space-y-4">
                  {[...thread].reverse().map((entry, i) => {
                    const style = THREAD_ACTION_STYLES[entry.action] ?? THREAD_ACTION_STYLES.proceed;
                    return (
                      <li key={i} className="pl-4">
                        <span
                          className="absolute -left-1.5 w-3 h-3 rounded-full border-2 border-surface"
                          style={{ background: persona.color }}
                        />
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={cn("inline-flex items-center px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider", style.cls)}>
                            {style.label}
                          </span>
                          <span className="font-mono text-[10px] text-text-muted">
                            {entry.completed_node_key}
                          </span>
                          <span className="text-[10px] text-text-faint ml-auto shrink-0">
                            {relTime(entry.created_at)}
                          </span>
                        </div>
                        {entry.reason && (
                          <p className="text-xs text-text-secondary mt-1 leading-snug">{entry.reason}</p>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
            </>
          )}

          {!loading && activeTab === "log" && (
            <>
              {decisions.length === 0 ? (
                <div className="text-sm text-text-muted py-6 text-center">
                  {t("conductor.panel.noLogYet")}
                </div>
              ) : (
                <ol className="relative border-l border-border-subtle ml-2 space-y-4">
                  {decisions.map((d) => {
                    const style = ACTION_STYLES[d.action] ?? ACTION_STYLES.proceed;
                    let diffObj: Record<string, unknown> | null = null;
                    if (d.diff_json) {
                      try { diffObj = JSON.parse(d.diff_json); } catch { diffObj = null; }
                    }
                    return (
                      <li key={d.id} className="pl-4">
                        <span
                          className="absolute -left-1.5 w-3 h-3 rounded-full border-2 border-surface"
                          style={{ background: persona.color }}
                        />
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={cn("inline-flex items-center px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider", style.cls)}>
                            {style.label}
                          </span>
                          <span className="text-[10px] text-text-faint ml-auto shrink-0">
                            {relTime(d.created_at)}
                          </span>
                        </div>
                        {d.reason && (
                          <p className="text-xs text-text-secondary mt-1 leading-snug">{d.reason}</p>
                        )}
                        {diffObj && (
                          <details className="mt-1.5">
                            <summary className="text-[10px] text-text-faint cursor-pointer select-none hover:text-text-muted">
                              {t("conductor.panel.graphDiff")}
                            </summary>
                            <pre className="mt-1 text-[10px] font-mono text-text-muted bg-surface-raised rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap">
                              {JSON.stringify(diffObj, null, 2)}
                            </pre>
                          </details>
                        )}
                        {d.applied_at && (
                          <div className="text-[10px] text-success mt-1">
                            {t("conductor.panel.applied", { time: relTime(d.applied_at) })}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
            </>
          )}

          {!loading && activeTab === "turns" && (
            <>
              {turns.length === 0 ? (
                <div className="text-sm text-text-muted py-6 text-center">
                  {t("conductor.panel.noTurnsYet")}
                </div>
              ) : (
                <ol className="relative border-l border-border-subtle ml-2 space-y-4">
                  {turns.map((turn) => {
                    const style = TURN_STYLES[turn.kind];
                    return (
                      <li key={turn.id} className={cn("pl-4", turn.kind === "user_message" && "ml-8")}>
                        <span
                          className="absolute -left-1.5 w-3 h-3 rounded-full border-2 border-surface"
                          style={{ background: persona.color }}
                        />
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={cn("inline-flex items-center px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider", style.cls)}>
                            {style.label}
                          </span>
                          {turn.kind !== "user_message" && (
                            <span className="font-mono text-[10px] text-text-secondary">
                              {t("conductor.panel.turnLabel", { turn: turn.turn_index + 1, sub: turn.sub_index })}
                            </span>
                          )}
                          <span className="text-[10px] text-text-faint ml-auto shrink-0">
                            {relTime(turn.created_at)}
                          </span>
                        </div>
                        <p className="text-xs text-text-secondary mt-1 leading-snug">
                          {formatTurnSummary(t, turn)}
                        </p>
                        <details className="mt-1.5">
                          <summary className="text-[10px] text-text-faint cursor-pointer select-none hover:text-text-muted">
                            {t("conductor.panel.payload")}
                          </summary>
                          <pre className="mt-1 text-[10px] font-mono text-text-muted bg-surface-raised rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap">
                            {JSON.stringify(turn.payload ?? {}, null, 2)}
                          </pre>
                        </details>
                      </li>
                    );
                  })}
                </ol>
              )}
            </>
          )}
        </div>

        <div className="shrink-0 border-t border-border-subtle px-5 py-4 bg-surface/80 backdrop-blur-sm">
          <div className="mb-2 text-[10px] font-black uppercase tracking-widest text-text-muted">
            {t("conductor.panel.messageConductor")}
          </div>
          <Textarea
            value={composer}
            onChange={(e) => setComposer(e.target.value)}
            placeholder={t("conductor.panel.messagePlaceholder")}
            rows={3}
            disabled={!hasActiveLoop || sending}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                void handleSend();
              }
            }}
          />
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-[11px] text-text-muted">
              {hasActiveLoop ? t("conductor.panel.queuedNoteHint") : t("conductor.panel.startLoopHint")}
            </p>
            <Button onClick={() => void handleSend()} disabled={!hasActiveLoop || sending || !composer.trim()}>
              {sending ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <SendHorizontal className="mr-1.5 h-3.5 w-3.5" />
              )}
              {t("conductor.panel.send")}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function formatTurnSummary(
  t: (key: string, params?: Record<string, string | number>) => string,
  turn: ConductorTurn,
): string {
  const payload = turn.payload ?? {};
  if (turn.kind === "llm_request") {
    return t("conductor.turnSummary.llmRequest", { count: Number(payload.message_count ?? 0) });
  }
  if (turn.kind === "llm_response") {
    return t("conductor.turnSummary.llmResponse", { stopReason: String(payload.stop_reason ?? "end_turn") });
  }
  if (turn.kind === "tool_use") {
    return t("conductor.turnSummary.toolUse", { name: String(payload.name ?? "unknown") });
  }
  if (turn.kind === "tool_result") {
    return t("conductor.turnSummary.toolResult", { name: String(payload.name ?? "Tool"), isError: payload.is_error ? "true" : "false" });
  }
  if (turn.kind === "user_message") {
    return t("conductor.turnSummary.userMessage");
  }
  if (turn.kind === "error") {
    return t("conductor.turnSummary.error");
  }
  return t("conductor.turnSummary.finalize", { status: String(payload.status ?? "done") });
}
