"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Pause, Play, SendHorizontal } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  getConductorLog,
  getConductorState,
  getConductorTurns,
  pauseConductor,
  resumeConductor,
  sendConductorMessage,
  type ConductorDecision,
  type ConductorStatePayload,
  type ConductorTurn,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { HistoryEntry } from "@/features/agents/dock/agentBus";
import { PERSONAS } from "@/features/agents/dock/personas";
import type { BusConductorStatusEvent, BusConductorTurnDeltaEvent, BusConductorTurnEvent } from "@/contexts/ExecutionProcessesContext";
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

export function ConductorLogPanel({ issueId, open, liveHistory, onClose }: Props) {
  const [decisions, setDecisions] = useState<ConductorDecision[]>([]);
  const [turns, setTurns] = useState<ConductorTurn[]>([]);
  const [conductorState, setConductorState] = useState<ConductorStatePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>("thread");
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [statusBusy, setStatusBusy] = useState<"pause" | "resume" | null>(null);
  const [streamingBuffers, setStreamingBuffers] = useState<StreamingBufferMap>({});
  const persona = PERSONAS["conductor"];
  const { t } = useI18n();
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
    ]).finally(() => setLoading(false));
  }, [issueId, open]);

  useEffect(() => {
    reload();
  }, [reload]);

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
    },
    enabled: open,
  });

  const thread = conductorState?.running_thread ?? [];
  const pending = conductorState?.pending_dispatches ?? [];
  const conductorStatus = conductorState?.conductor_status ?? "idle";
  const conductorPhase = conductorState?.phase ?? null;
  const phaseStartedAt = conductorState?.updated_at ? new Date(conductorState.updated_at).getTime() : null;
  const phaseElapsedSeconds = phaseStartedAt ? Math.max(0, Math.floor((Date.now() - phaseStartedAt) / 1000)) : 0;
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
      <SheetContent side="right" className="w-[480px] sm:w-[540px] flex flex-col gap-0 p-0">
        <SheetHeader className="px-5 pt-4 pb-3 shrink-0 border-b border-border-subtle">
          <div className="flex items-start gap-3">
            <SheetTitle className="flex items-center gap-3 text-lg">
              <span
                className="w-10 h-10 rounded-full flex items-center justify-center text-2xl border-2"
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
                "mt-3 rounded-2xl border px-3 py-2 text-xs",
                stuck ? "border-warning/50 bg-warning/10 text-warning" : "border-border-subtle bg-surface-raised text-text-secondary",
              )}
            >
              {conductorPhase && (
                <div className="font-mono text-[11px] uppercase tracking-wider">
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

        <div className="flex border-b border-border-subtle shrink-0">
          {(["thread", "log", "turns"] as TabId[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-5 py-2.5 text-[11px] font-black uppercase tracking-widest transition-colors",
                activeTab === tab
                  ? "border-b-2 text-brand"
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

        <div className="shrink-0 border-t border-border-subtle px-5 py-4">
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
