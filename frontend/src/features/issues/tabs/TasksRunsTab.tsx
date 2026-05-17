"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  chatCodexTask,
  getCodexTasks,
  getExecutionProcesses,
  getRuntimeCatalog,
  refineCodexTask,
  rerunCodexTask,
  runCodexTask,
  terminateCodexTask,
  updateCodexTask,
} from "@/lib/api";
import { useExecutionProcessLogStream } from "@/hooks/useExecutionProcessLogStream";
import { useExecutionProcessMessageStream } from "@/hooks/useExecutionProcessMessageStream";
import type { CodexIssue, CodexTask, CodexTaskMessage, ExecutionProcess, RuntimeCatalog } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { ExecutionConfigSelector, normalizeExecutionConfig, type ExecutionConfigValue } from "@/components/runtime/ExecutionConfigSelector";
import { EmptyState } from "@/components/ui/empty-state";
import { cn } from "@/lib/utils";
import { AgentLiveTimeline } from "@/features/runs/AgentLiveTimeline";

interface Props {
  issueId: string;
  issue: CodexIssue | null;
}

type RunMode = "chat" | "refine" | "rerun";

const ISSUE_TERMINAL = new Set(["completed", "failed", "cancelled", "abandoned"]);

export function TasksRunsTab({ issueId, issue }: Props) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const params = useSearchParams();
  const initialTaskId = params.get("taskId");
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(initialTaskId);
  const [runs, setRuns] = useState<ExecutionProcess[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [mode, setMode] = useState<RunMode>("chat");
  const [composer, setComposer] = useState("");
  const [busy, setBusy] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [streamView, setStreamView] = useState<"live" | "raw" | "assistant">("live");
  const [catalog, setCatalog] = useState<RuntimeCatalog | null>(null);
  // Initial config is intentionally minimal — once the catalog loads or a task
  // is selected, normalizeExecutionConfig() resolves the right enabled executor id.
  const [config, setConfig] = useState<ExecutionConfigValue>({ executor: "", provider: null, model: null });

  useEffect(() => {
    void getRuntimeCatalog().then(setCatalog).catch(() => setCatalog(null));
  }, []);

  const loadTasks = useCallback(async () => {
    try {
      const list = await getCodexTasks(null, issueId);
      setTasks(list);
      if (!selectedTaskId && list.length > 0) setSelectedTaskId(list[0].id);
    } catch (err) {
      addToast({ type: "error", title: "Failed to load tasks", message: err instanceof Error ? err.message : String(err) });
    }
  }, [issueId, selectedTaskId, addToast]);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks]);

  // Re-select task when URL ?taskId=... changes (e.g. user clicks a node in
  // the DAG tab which routes here with the task pre-targeted).
  useEffect(() => {
    if (initialTaskId && initialTaskId !== selectedTaskId) {
      setSelectedTaskId(initialTaskId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTaskId]);

  const loadRuns = useCallback(async (taskId: string) => {
    try {
      const list = await getExecutionProcesses(null, taskId);
      const sorted = [...list].sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""));
      setRuns(sorted);
      if (sorted.length > 0) setSelectedRunId(sorted[0].id);
      else setSelectedRunId(null);
    } catch {
      setRuns([]);
      setSelectedRunId(null);
    }
  }, []);

  useEffect(() => {
    if (selectedTaskId) void loadRuns(selectedTaskId);
  }, [selectedTaskId, loadRuns]);

  // Periodic refresh while anything is live. Also covers the gap where the
  // issue is in-progress but the scheduler hasn't created the next task yet —
  // without checking issue.status, the poll would stop after PM completes and
  // Architect/Engineer/QA tasks would never appear.
  useEffect(() => {
    const issueActive = issue != null && !ISSUE_TERMINAL.has(issue.status);
    const hasLive =
      issueActive ||
      tasks.some((t) => t.status === "running" || t.status === "responding" || t.status === "pending") ||
      runs.some((r) => r.status === "running" || r.status === "in_progress");
    if (!hasLive) return;
    const id = window.setInterval(() => {
      void loadTasks();
      if (selectedTaskId) void loadRuns(selectedTaskId);
    }, 3000);
    return () => window.clearInterval(id);
  }, [issue, tasks, runs, selectedTaskId, loadTasks, loadRuns]);

  const selectedTask = useMemo(() => tasks.find((t) => t.id === selectedTaskId) ?? null, [tasks, selectedTaskId]);
  const selectedRun = useMemo(() => runs.find((r) => r.id === selectedRunId) ?? null, [runs, selectedRunId]);

  // Re-normalize config whenever the catalog or selected task changes.
  // normalizeExecutionConfig falls back to the first enabled executor when the
  // task's stored executor isn't in the catalog (e.g. legacy "codex" string on
  // a catalog that only has a "claude"-type minimax executor).
  useEffect(() => {
    if (!catalog) return;
    const seedExecutor = selectedTask?.executor ?? "";
    const seedProvider = selectedTask?.provider ?? null;
    const seedModel = selectedTask?.model ?? null;
    setConfig(normalizeExecutionConfig(catalog, seedExecutor, seedProvider, seedModel));
  }, [catalog, selectedTask]);

  const { logs } = useExecutionProcessLogStream(selectedRunId);
  const { messages, pendingAssistant } = useExecutionProcessMessageStream(selectedRunId);

  // A task is "fresh" if it has never been executed — show a primary Run
  // button instead of the chat/refine/rerun composer.
  const isFreshTask = useMemo(() => {
    if (!selectedTask) return false;
    if (runs.length > 0) return false;
    return (
      selectedTask.status === "pending" ||
      selectedTask.status === "queued" ||
      selectedTask.status === "blocked" ||
      selectedTask.status === "ready"
    );
  }, [selectedTask, runs]);

  const handleRunFresh = useCallback(async () => {
    if (!selectedTaskId) return;
    setBusy(true);
    try {
      // Persist the per-task executor/provider/model first so the run picks them up.
      await updateCodexTask(selectedTaskId, config.executor, config.provider, config.model);
      await runCodexTask(selectedTaskId, {
        executor: config.executor,
        provider: config.provider,
        model: config.model,
      });
      addToast({ type: "success", title: "Run dispatched" });
      void loadTasks();
      void loadRuns(selectedTaskId);
    } catch (err) {
      addToast({ type: "error", title: "Run failed", message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }, [selectedTaskId, config, addToast, loadTasks, loadRuns]);

  const send = useCallback(async () => {
    if (!selectedTaskId) return;
    const content = composer.trim();
    if (mode !== "rerun" && !content) return;
    setBusy(true);
    try {
      if (mode === "rerun") {
        await updateCodexTask(selectedTaskId, config.executor, config.provider, config.model);
        await rerunCodexTask(selectedTaskId, {
          executor: config.executor,
          provider: config.provider,
          model: config.model,
        });
      } else if (mode === "refine") {
        await refineCodexTask(selectedTaskId, content);
      } else {
        await chatCodexTask(selectedTaskId, content);
      }
      setComposer("");
      addToast({ type: "success", title: `${mode} dispatched` });
      void loadTasks();
      void loadRuns(selectedTaskId);
    } catch (err) {
      addToast({ type: "error", title: `${mode} failed`, message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }, [selectedTaskId, composer, mode, config, addToast, loadTasks, loadRuns]);

  const handleTerminate = useCallback(async () => {
    if (!selectedTaskId) return;
    try {
      await terminateCodexTask(selectedTaskId);
      addToast({ type: "success", title: "Terminated" });
      void loadRuns(selectedTaskId);
    } catch (err) {
      addToast({ type: "error", title: "Failed to terminate", message: err instanceof Error ? err.message : String(err) });
    }
  }, [selectedTaskId, loadRuns, addToast]);

  return (
    <div className="h-full flex flex-col min-h-0 flex-1">
      <div className="flex-1 min-h-[500px] h-[650px] lg:h-[calc(100vh-320px)] grid grid-cols-[220px_240px_1fr] gap-px bg-border-subtle">
        <div className="bg-surface overflow-y-auto flex flex-col min-h-0">
          <div className="p-3 text-[10px] font-black uppercase tracking-widest text-text-muted shrink-0">Tasks</div>
          {tasks.length === 0 && (
            <div className="flex-1 flex items-center justify-center">
              <EmptyState
                icon="task"
                title="No tasks yet"
                description="Tasks appear here when the workflow DAG starts."
              />
            </div>
          )}
          {tasks.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setSelectedTaskId(t.id)}
              className={cn(
                "w-full text-left px-3 py-2 text-sm border-l-2 transition-colors",
                t.id === selectedTaskId ? "border-brand bg-brand/5" : "border-transparent hover:bg-surface-hover"
              )}
            >
              <div className="truncate">{t.title}</div>
              <div className="flex items-center gap-2 text-[10px] text-text-muted mt-0.5">
                <span>{t.role}</span>
                <span>·</span>
                <StatusDot status={t.status} />
                <span>{t.status}</span>
              </div>
            </button>
          ))}
        </div>

        <div className="bg-surface overflow-y-auto flex flex-col min-h-0">
          <div className="p-3 text-[10px] font-black uppercase tracking-widest text-text-muted shrink-0">Runs</div>
          {runs.length === 0 && (
            <div className="flex-1 flex items-center justify-center">
              <EmptyState
                icon="log"
                title={selectedTaskId ? "No runs yet" : "No task selected"}
                description={selectedTaskId ? "Click Run in the composer below to start." : "Select a task on the left."}
              />
            </div>
          )}
          {runs.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setSelectedRunId(r.id)}
              className={cn(
                "w-full text-left px-3 py-2 text-xs border-l-2 transition-colors",
                r.id === selectedRunId ? "border-brand bg-brand/5" : "border-transparent hover:bg-surface-hover"
              )}
            >
              <div className="flex items-center gap-2">
                <span className="font-bold uppercase">{r.kind ?? "run"}</span>
                <StatusDot status={r.status} />
                <span className="text-text-muted">{r.status}</span>
              </div>
              <div className="text-[10px] text-text-muted mt-0.5 font-mono truncate">
                {r.executor}/{r.model ?? "—"} · {r.started_at?.slice(11, 19) ?? "—"}
              </div>
            </button>
          ))}
        </div>

        <div className="bg-background flex flex-col min-h-0">
          {selectedRunId && (
            <div className="px-4 pt-3 pb-2 flex items-center gap-2 border-b border-border-subtle">
              <span className="text-[10px] font-black uppercase tracking-widest text-text-muted">View</span>
              <button
                type="button"
                onClick={() => setStreamView("live")}
                className={cn(
                  "px-2 py-0.5 text-[11px] font-bold rounded border",
                  streamView === "live"
                    ? "border-brand bg-brand text-background"
                    : "border-border-subtle text-text-muted hover:text-foreground"
                )}
              >
                Live
              </button>
              <button
                type="button"
                onClick={() => setStreamView("assistant")}
                className={cn(
                  "px-2 py-0.5 text-[11px] font-bold rounded border",
                  streamView === "assistant"
                    ? "border-brand bg-brand text-background"
                    : "border-border-subtle text-text-muted hover:text-foreground"
                )}
              >
                Assistant text
              </button>
              <button
                type="button"
                onClick={() => setStreamView("raw")}
                className={cn(
                  "px-2 py-0.5 text-[11px] font-bold rounded border",
                  streamView === "raw"
                    ? "border-brand bg-brand text-background"
                    : "border-border-subtle text-text-muted hover:text-foreground"
                )}
              >
                Raw stream
              </button>
            </div>
          )}
          <div className="flex-1 min-h-0 overflow-y-auto p-4 font-mono text-xs leading-relaxed flex flex-col">
            {!selectedRunId && messages.length === 0 && (
              <div className="h-full flex items-center justify-center">
                <EmptyState
                  icon="message"
                  title="No run selected"
                  description="Pick a run on the left to watch its live log and messages."
                />
              </div>
            )}
            {streamView === "live" ? (
              <AgentLiveTimeline
                executionProcessId={selectedRunId}
                taskStartedAt={selectedRun?.started_at ?? null}
                taskStatus={selectedTask?.status ?? null}
                reviewComment={selectedTask?.review_comment ?? null}
                taskResult={selectedTask?.result ?? null}
                taskRole={selectedTask?.role ?? null}
                onRerun={
                  selectedTaskId
                    ? async () => {
                        try {
                          await rerunCodexTask(selectedTaskId);
                          addToast({ type: "success", title: t("agentLive.rerunOk") });
                          void loadTasks();
                          void loadRuns(selectedTaskId);
                        } catch (err) {
                          addToast({
                            type: "error",
                            title: t("agentLive.rerunErr"),
                            message: err instanceof Error ? err.message : String(err),
                          });
                        }
                      }
                    : undefined
                }
                onStop={
                  selectedTaskId
                    ? async () => {
                        if (!window.confirm(t("agentLive.stopConfirm"))) return;
                        try {
                          await terminateCodexTask(selectedTaskId);
                          addToast({ type: "success", title: t("agentLive.stopOk") });
                          void loadTasks();
                          void loadRuns(selectedTaskId);
                        } catch (err) {
                          addToast({
                            type: "error",
                            title: t("agentLive.stopErr"),
                            message: err instanceof Error ? err.message : String(err),
                          });
                        }
                      }
                    : undefined
                }
                className="h-full"
              />
            ) : streamView === "assistant" ? (
              <>
                {extractAssistantText(messages, pendingAssistant).map((entry, i) => (
                  <div key={`asst-${i}`} className="mb-3">
                    <div className="text-[10px] uppercase text-text-muted mb-1">{entry.role}{entry.live ? " (live)" : ""}</div>
                    <div className="whitespace-pre-wrap text-text-primary break-words">{entry.text}</div>
                  </div>
                ))}
                {messages.length === 0 && !pendingAssistant && logs.length > 0 && (
                  <div className="text-text-muted text-[10px]">
                    No assistant text yet — switch to <b>Raw stream</b> to see protocol frames.
                  </div>
                )}
              </>
            ) : (
              <>
                {messages.map((m) => (
                  <div key={m.id} className="mb-2">
                    <div className="text-[10px] uppercase text-text-muted">{m.role}</div>
                    <div className="whitespace-pre-wrap break-words">{m.content}</div>
                  </div>
                ))}
                {pendingAssistant && (
                  <div className="mb-2">
                    <div className="text-[10px] uppercase text-text-muted">assistant (live)</div>
                    <div className="whitespace-pre-wrap break-words">{pendingAssistant.text}</div>
                  </div>
                )}
                {messages.length === 0 && logs.length > 0 && (
                  <div className="text-text-muted break-all">
                    {logs.slice(-50).map((l) => (
                      <div key={l.id} className="mb-1">{l.content?.slice(0, 200)}</div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          <div className="border-t border-border-subtle p-3 bg-surface flex flex-col gap-2 shrink-0">
            {isFreshTask ? (
              <>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-text-muted">
                    Task has not run yet · status: <b>{selectedTask?.status}</b>
                  </span>
                  <button
                    type="button"
                    onClick={() => setConfigOpen((v) => !v)}
                    className="ml-auto text-[10px] font-mono text-text-muted hover:text-foreground underline"
                  >
                    {config.executor}/{config.model ?? "default"}
                  </button>
                </div>
                {configOpen && (
                  <div className="p-2 rounded border border-border-subtle bg-surface-raised">
                    <ExecutionConfigSelector value={config} onChange={setConfig} catalog={catalog} />
                  </div>
                )}
                <div className="flex justify-end">
                  <Button onClick={() => void handleRunFresh()} disabled={busy || !selectedTaskId}>
                    {busy ? "Starting…" : "Run"}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <ModeButton current={mode} value="chat" onClick={() => setMode("chat")} hint={t("task.runMode.chatHint")} />
                  <ModeButton current={mode} value="refine" onClick={() => setMode("refine")} hint={t("task.runMode.refineHint")} />
                  <ModeButton current={mode} value="rerun" onClick={() => setMode("rerun")} hint={t("task.runMode.autoHint")} />
                  <button
                    type="button"
                    onClick={() => setConfigOpen((v) => !v)}
                    className="ml-auto text-[10px] font-mono text-text-muted hover:text-foreground underline"
                  >
                    {config.executor}/{config.model ?? "default"}
                  </button>
                  {selectedRun?.status === "running" && (
                    <Button variant="outline" size="sm" onClick={() => void handleTerminate()}>
                      Terminate
                    </Button>
                  )}
                </div>
                {configOpen && (
                  <div className="p-2 rounded border border-border-subtle bg-surface-raised">
                    <ExecutionConfigSelector value={config} onChange={setConfig} catalog={catalog} />
                  </div>
                )}
                {mode !== "rerun" && (
                  <textarea
                    value={composer}
                    onChange={(e) => setComposer(e.target.value)}
                    placeholder={mode === "refine" ? "Describe the changes to apply…" : "Send a message…"}
                    rows={2}
                    className="w-full bg-surface-input border border-border-subtle rounded-md px-3 py-2 text-sm outline-none focus:border-brand resize-y"
                  />
                )}
                <div className="flex justify-end">
                  <Button onClick={() => void send()} disabled={busy || !selectedTaskId || (mode !== "rerun" && !composer.trim())}>
                    {busy ? "Sending…" : mode === "rerun" ? "Rerun" : mode === "refine" ? "Refine" : "Send"}
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "done" || status === "passed"
      ? "bg-success"
      : status === "failed" || status === "error"
        ? "bg-error"
        : status === "running" || status === "in_progress"
          ? "bg-warning animate-pulse"
          : "bg-text-muted";
  return <span className={cn("inline-block size-2 rounded-full", color)} />;
}

function ModeButton({
  current,
  value,
  onClick,
  hint,
}: {
  current: RunMode;
  value: RunMode;
  onClick: () => void;
  hint: string;
}) {
  const active = current === value;
  return (
    <button
      type="button"
      onClick={onClick}
      title={hint}
      className={cn(
        "px-2 py-1 text-[11px] font-bold uppercase tracking-wider rounded border transition-colors",
        active
          ? "border-brand bg-brand text-background"
          : "border-border-subtle text-text-muted hover:text-foreground hover:bg-surface-hover"
      )}
    >
      {value}
    </button>
  );
}

interface AssistantEntry {
  role: string;
  text: string;
  live: boolean;
}

/**
 * Pull the readable assistant prose out of a Codex/Claude SDK message log.
 * The raw `messages` are full protocol envelopes — many of them are tool
 * calls / tool results / streaming envelopes whose `content` is a giant
 * JSON-RPC blob. This filter returns just the human-readable text the
 * model produced, role-tagged, in arrival order.
 */
function extractAssistantText(
  messages: CodexTaskMessage[],
  pending: { text: string; lastSeq: number } | null,
): AssistantEntry[] {
  const out: AssistantEntry[] = [];
  for (const m of messages) {
    if (m.role !== "assistant" && m.role !== "user") continue;
    const text = humanReadable(m.content);
    if (text) out.push({ role: m.role, text, live: false });
  }
  if (pending && pending.text) {
    out.push({ role: "assistant", text: pending.text, live: true });
  }
  return out;
}

/**
 * Best-effort extraction of human text from a Codex/Claude SDK message
 * `content` field. The field is sometimes a plain string, sometimes a JSON
 * envelope with `{type:"assistant", message:{content:[{type:"text", text:...}]}}`.
 * Walk the JSON if possible; otherwise return the raw string trimmed.
 */
function humanReadable(content: string): string {
  if (!content) return "";
  const trimmed = content.trim();
  // Try JSON-envelope path.
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const obj = JSON.parse(trimmed);
      const collected: string[] = [];
      const walk = (n: unknown) => {
        if (!n) return;
        if (typeof n === "string") return;
        if (Array.isArray(n)) {
          n.forEach(walk);
          return;
        }
        if (typeof n === "object") {
          const node = n as Record<string, unknown>;
          if (node.type === "text" && typeof node.text === "string") {
            collected.push(node.text);
          }
          if (node.type === "thinking" && typeof node.thinking === "string") {
            // Thinking blocks are useful to surface in "assistant text"
            // mode for transparency; prefix so they're distinguishable.
            collected.push(`[thinking] ${node.thinking}`);
          }
          if (node.type === "tool_use") {
            const name = node.name ?? "tool";
            collected.push(`[tool: ${String(name)}]`);
          }
          if (node.type === "tool_result") {
            collected.push("[tool result]");
          }
          Object.values(node).forEach(walk);
        }
      };
      walk(obj);
      if (collected.length > 0) return collected.join("\n").trim();
    } catch {
      // fall through
    }
  }
  return trimmed;
}
