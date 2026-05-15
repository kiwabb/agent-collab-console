"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  chatCodexTask,
  getCodexTasks,
  getExecutionProcesses,
  getRuntimeCatalog,
  refineCodexTask,
  rerunCodexTask,
  terminateCodexTask,
  updateCodexTask,
} from "@/lib/api";
import { useExecutionProcessLogStream } from "@/hooks/useExecutionProcessLogStream";
import { useExecutionProcessMessageStream } from "@/hooks/useExecutionProcessMessageStream";
import type { CodexIssue, CodexTask, ExecutionProcess, RuntimeCatalog } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { ExecutionConfigSelector, getFallbackConfig, type ExecutionConfigValue } from "@/components/runtime/ExecutionConfigSelector";
import { cn } from "@/lib/utils";

interface Props {
  issueId: string;
  issue: CodexIssue | null;
}

type RunMode = "chat" | "refine" | "rerun";

export function TasksRunsTab({ issueId, issue: _issue }: Props) {
  void _issue;
  const { addToast } = useToast();
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [runs, setRuns] = useState<ExecutionProcess[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [mode, setMode] = useState<RunMode>("chat");
  const [composer, setComposer] = useState("");
  const [busy, setBusy] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [catalog, setCatalog] = useState<RuntimeCatalog | null>(null);
  const [config, setConfig] = useState<ExecutionConfigValue>(() => getFallbackConfig(null, "codex", null, null));

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

  const selectedTask = useMemo(() => tasks.find((t) => t.id === selectedTaskId) ?? null, [tasks, selectedTaskId]);
  const selectedRun = useMemo(() => runs.find((r) => r.id === selectedRunId) ?? null, [runs, selectedRunId]);

  useEffect(() => {
    if (selectedTask) {
      setConfig({
        executor: selectedTask.executor ?? "codex",
        provider: selectedTask.provider ?? null,
        model: selectedTask.model ?? null,
      });
    }
  }, [selectedTask]);

  const { logs } = useExecutionProcessLogStream(selectedRunId);
  const { messages, pendingAssistant } = useExecutionProcessMessageStream(selectedRunId);

  const send = useCallback(async () => {
    if (!selectedTaskId) return;
    const content = composer.trim();
    if (mode !== "rerun" && !content) return;
    setBusy(true);
    try {
      if (mode === "rerun") {
        const executor = (config.executor === "claude" ? "claude" : "codex") as "codex" | "claude";
        await updateCodexTask(selectedTaskId, executor, config.provider, config.model);
        await rerunCodexTask(selectedTaskId, {
          executor,
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
    <div className="h-full flex flex-col">
      <div className="flex-1 min-h-0 grid grid-cols-[220px_240px_1fr] gap-px bg-border-subtle">
        <div className="bg-surface overflow-auto">
          <div className="p-3 text-[10px] font-black uppercase tracking-widest text-text-muted">Tasks</div>
          {tasks.length === 0 && <div className="px-3 text-xs text-text-muted">No tasks</div>}
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

        <div className="bg-surface overflow-auto">
          <div className="p-3 text-[10px] font-black uppercase tracking-widest text-text-muted">Runs</div>
          {runs.length === 0 && <div className="px-3 text-xs text-text-muted">No runs yet</div>}
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
          <div className="flex-1 overflow-auto p-4 font-mono text-xs leading-relaxed">
            {!selectedRunId && <div className="text-text-muted">Select a run to view its stream</div>}
            {messages.map((m) => (
              <div key={m.id} className="mb-2">
                <div className="text-[10px] uppercase text-text-muted">{m.role}</div>
                <div className="whitespace-pre-wrap">{m.content}</div>
              </div>
            ))}
            {pendingAssistant && (
              <div className="mb-2">
                <div className="text-[10px] uppercase text-text-muted">assistant (live)</div>
                <div className="whitespace-pre-wrap">{pendingAssistant.text}</div>
              </div>
            )}
            {messages.length === 0 && logs.length > 0 && (
              <div className="text-text-muted">
                {logs.slice(-50).map((l) => (
                  <div key={l.id}>{l.content?.slice(0, 200)}</div>
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-border-subtle p-3 bg-surface flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <ModeButton current={mode} value="chat" onClick={() => setMode("chat")} hint="Chat 不修改产物" />
              <ModeButton current={mode} value="refine" onClick={() => setMode("refine")} hint="Refine 在现有产物上迭代" />
              <ModeButton current={mode} value="rerun" onClick={() => setMode("rerun")} hint="Rerun 从原始 prompt 重跑" />
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
