"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  getConductorLog,
  getConductorState,
  getConductorTurns,
  type ConductorDecision,
  type ConductorStatePayload,
  type ConductorTurn,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { HistoryEntry } from "@/features/agents/dock/agentBus";
import { PERSONAS } from "@/features/agents/dock/personas";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

interface Props {
  issueId: string;
  open: boolean;
  liveHistory: HistoryEntry[];
  onClose: () => void;
}

type TabId = "thread" | "log" | "turns";

const THREAD_ACTION_STYLES: Record<string, { label: string; cls: string }> = {
  proceed: { label: "Proceed", cls: "bg-surface-raised text-text-secondary border-border-subtle" },
  note: { label: "Note", cls: "bg-info/10 text-info border-info/30" },
  escalate: { label: "Escalate", cls: "bg-error/10 text-error border-error/30" },
  dispatch_next: { label: "Dispatch Next", cls: "bg-brand/10 text-brand border-brand/30" },
  inject_context: { label: "Inject Context", cls: "bg-warning/10 text-warning border-warning/30" },
  spawn_specialist: { label: "Spawn Specialist", cls: "bg-success/10 text-success border-success/30" },
  spawn_custom: { label: "Spawn Custom", cls: "bg-success/10 text-success border-success/30" },
};

const ACTION_STYLES: Record<ConductorDecision["action"], { label: string; cls: string }> = {
  proceed: { label: "Proceed", cls: "bg-surface-raised text-text-secondary border-border-subtle" },
  note: { label: "Note", cls: "bg-info/10 text-info border-info/30" },
  escalate: { label: "Escalate", cls: "bg-error/10 text-error border-error/30" },
  reroute: { label: "Reroute", cls: "bg-brand/10 text-brand border-brand/30" },
  insert_node: { label: "Insert Node", cls: "bg-success/10 text-success border-success/30" },
  request_clarification: { label: "Clarify", cls: "bg-warning/10 text-warning border-warning/30" },
};

const TURN_STYLES: Record<ConductorTurn["kind"], { label: string; cls: string }> = {
  llm_request: { label: "LLM", cls: "bg-brand/10 text-brand border-brand/30" },
  tool_use: { label: "Tool", cls: "bg-warning/10 text-warning border-warning/30" },
  tool_result: { label: "Result", cls: "bg-success/10 text-success border-success/30" },
  error: { label: "Error", cls: "bg-error/10 text-error border-error/30" },
  finalize: { label: "Done", cls: "bg-surface-raised text-text-secondary border-border-subtle" },
};

function relTime(iso: string | null): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 1000) return "just now";
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  return `${Math.floor(ms / 3_600_000)}h ago`;
}

export function ConductorLogPanel({ issueId, open, liveHistory, onClose }: Props) {
  const [decisions, setDecisions] = useState<ConductorDecision[]>([]);
  const [turns, setTurns] = useState<ConductorTurn[]>([]);
  const [conductorState, setConductorState] = useState<ConductorStatePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>("thread");
  const persona = PERSONAS["conductor"];

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
      const turn = evt as ConductorTurn;
      setTurns((prev) => {
        if (prev.some((entry) => entry.id === turn.id)) return prev;
        return [...prev, turn];
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

  const thread = conductorState?.running_thread ?? [];
  const pending = conductorState?.pending_dispatches ?? [];

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[480px] sm:w-[540px] flex flex-col gap-0 p-0">
        <SheetHeader className="px-5 pt-4 pb-3 shrink-0 border-b border-border-subtle">
          <SheetTitle className="flex items-center gap-3 text-lg">
            <span
              className="w-10 h-10 rounded-full flex items-center justify-center text-2xl border-2"
              style={{ borderColor: persona.color, background: `${persona.color}11` }}
              aria-hidden
            >
              {persona.emoji}
            </span>
            {persona.name}
          </SheetTitle>
          <SheetDescription className="text-xs text-text-muted">
            {persona.blurb}
          </SheetDescription>
        </SheetHeader>

        {liveHistory.length > 0 && (
          <div className="px-5 py-3 border-b border-border-subtle shrink-0">
            <div className="text-[10px] font-black uppercase tracking-widest text-text-muted mb-2">
              Live · {liveHistory.length} events
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
                ? `Conductor Thread (${thread.length})`
                : tab === "log"
                  ? `Decision Log (${decisions.length})`
                  : `Turns (${turns.length})`}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-auto px-5 py-4">
          {loading && (
            <div className="text-sm text-text-muted py-6 text-center">Loading…</div>
          )}

          {!loading && activeTab === "thread" && (
            <>
              {pending.length > 0 && (
                <div className="mb-4 rounded-2xl border border-brand/20 bg-brand/5 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-brand mb-2">
                    {pending.length} pending dispatch{pending.length > 1 ? "es" : ""}
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
                    Scratchpad ▸
                  </summary>
                  <p className="mt-2 text-xs text-text-secondary bg-surface-raised rounded-xl px-3 py-2 leading-relaxed whitespace-pre-wrap">
                    {conductorState.scratchpad}
                  </p>
                </details>
              )}

              {thread.length === 0 ? (
                <div className="text-sm text-text-muted py-6 text-center">
                  No decisions in thread yet. Conductor records state after each task completes.
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
                  No decisions recorded yet.
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
                              Graph diff ▸
                            </summary>
                            <pre className="mt-1 text-[10px] font-mono text-text-muted bg-surface-raised rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap">
                              {JSON.stringify(diffObj, null, 2)}
                            </pre>
                          </details>
                        )}
                        {d.applied_at && (
                          <div className="text-[10px] text-success mt-1">
                            Applied {relTime(d.applied_at)}
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
                  No conductor turns recorded yet.
                </div>
              ) : (
                <ol className="relative border-l border-border-subtle ml-2 space-y-4">
                  {turns.map((turn) => {
                    const style = TURN_STYLES[turn.kind];
                    return (
                      <li key={turn.id} className="pl-4">
                        <span
                          className="absolute -left-1.5 w-3 h-3 rounded-full border-2 border-surface"
                          style={{ background: persona.color }}
                        />
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={cn("inline-flex items-center px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider", style.cls)}>
                            {style.label}
                          </span>
                          <span className="font-mono text-[10px] text-text-secondary">
                            turn {turn.turn_index + 1}.{turn.sub_index}
                          </span>
                          <span className="text-[10px] text-text-faint ml-auto shrink-0">
                            {relTime(turn.created_at)}
                          </span>
                        </div>
                        <p className="text-xs text-text-secondary mt-1 leading-snug">
                          {formatTurnSummary(turn)}
                        </p>
                        <details className="mt-1.5">
                          <summary className="text-[10px] text-text-faint cursor-pointer select-none hover:text-text-muted">
                            Payload ▸
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
      </SheetContent>
    </Sheet>
  );
}

function formatTurnSummary(turn: ConductorTurn): string {
  const payload = turn.payload ?? {};
  if (turn.kind === "llm_request") {
    return `Prepared an LLM call with ${String(payload.message_count ?? 0)} messages.`;
  }
  if (turn.kind === "tool_use") {
    return `Called ${String(payload.name ?? "unknown")} with the current turn context.`;
  }
  if (turn.kind === "tool_result") {
    return `${String(payload.name ?? "Tool")} returned ${payload.is_error ? "an error" : "a result"}.`;
  }
  if (turn.kind === "error") {
    return String(payload.message ?? payload.error_class ?? "Conductor crashed.");
  }
  return `Loop finalized with status ${String(payload.status ?? "done")}.`;
}
