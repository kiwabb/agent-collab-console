"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Play, RadioTower, Wrench } from "lucide-react";

import { API_BASE, startProjectConductorLoop } from "@/lib/api";
import type { ProjectConductorLoopResult, ProjectConductorToolEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";

type ThreadEvent = {
  id: string;
  role: string;
  content: string;
  status?: string;
  tool_events?: ProjectConductorToolEvent[];
};

export function ProjectConductorThreadDock({ projectId, onLoopDone }: { projectId: string; onLoopDone?: () => void }) {
  const { addToast } = useToast();
  const { t } = useI18n();
  const [prompt, setPrompt] = useState("");
  const [running, setRunning] = useState(false);
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<ThreadEvent[]>([]);
  const [tools, setTools] = useState<ProjectConductorToolEvent[]>([]);
  const [latestResult, setLatestResult] = useState<ProjectConductorLoopResult | null>(null);
  const isProjectConductorStreaming = connected || running;

  const streamUrl = useMemo(
    () => `${API_BASE}/codex/projects/${encodeURIComponent(projectId)}/conductor/stream`,
    [projectId],
  );

  const connectStream = useCallback(() => {
    const source = new EventSource(streamUrl);
    source.addEventListener("open", () => setConnected(true));
    source.addEventListener("event", (message) => {
      try {
        const parsed = JSON.parse((message as MessageEvent).data) as Record<string, unknown>;
        setEvents((prev) => [
          {
            id: String(parsed.task_id ?? parsed.created_at ?? `${Date.now()}-${prev.length}`),
            role: String(parsed.role ?? "project_conductor"),
            content: String(parsed.content ?? ""),
            status: typeof parsed.status === "string" ? parsed.status : undefined,
            tool_events: Array.isArray(parsed.tool_events) ? (parsed.tool_events as ProjectConductorToolEvent[]) : [],
          },
          ...prev,
        ].slice(0, 12));
      } catch {
        // Ignore malformed replay rows; the next event can still render.
      }
    });
    source.addEventListener("tool", (message) => {
      try {
        setTools((prev) => [JSON.parse((message as MessageEvent).data) as ProjectConductorToolEvent, ...prev].slice(0, 12));
      } catch {
        // Ignore malformed tool cards.
      }
    });
    source.addEventListener("done", () => {
      setConnected(false);
      source.close();
    });
    source.onerror = () => {
      setConnected(false);
      source.close();
    };
    return source;
  }, [streamUrl]);

  useEffect(() => {
    const source = connectStream();
    return () => source.close();
  }, [connectStream]);

  const handleStartLoop = useCallback(async () => {
    setRunning(true);
    try {
      const result = await startProjectConductorLoop(projectId, prompt.trim() || undefined);
      setLatestResult(result);
      setTools((prev) => [...result.tool_events, ...prev].slice(0, 12));
      setPrompt("");
      onLoopDone?.();
      const source = connectStream();
      setTimeout(() => source.close(), 2500);
    } catch (err) {
      addToast({
        type: "error",
        title: t("projectConductor.toast.loopFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRunning(false);
    }
  }, [projectId, prompt, onLoopDone, connectStream, addToast, t]);

  return (
    <div
      data-density="project-conductor-thread-dock"
      className={cn(
        "relative overflow-hidden rounded-2xl border border-border-subtle bg-surface/75 p-4 shadow-inner shadow-black/5 transition-colors",
        isProjectConductorStreaming && "motion-essential border-brand/35 bg-brand-muted/10",
      )}
    >
      {isProjectConductorStreaming && (
        <span
          aria-hidden
          className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
        />
      )}
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "size-9 rounded-2xl border border-brand/20 bg-brand/10 flex items-center justify-center text-brand transition-colors",
              isProjectConductorStreaming && "border-brand/35 bg-brand/15",
            )}
          >
            <RadioTower size={17} />
          </div>
          <div>
            <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted">{t("projectConductor.threadDock.title")}</h3>
            <p className="mt-1 text-xs text-text-muted">
              {connected ? t("projectConductor.threadDock.listening") : t("projectConductor.threadDock.replayHint")}
            </p>
          </div>
        </div>
        <div
          className={cn(
            "flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-text-muted transition-colors",
            isProjectConductorStreaming && "text-brand",
          )}
        >
          {isProjectConductorStreaming ? (
            <AgentThinkingIndicator phase={running ? "dispatching" : "streaming"} size={14} />
          ) : (
            <span aria-hidden className="size-2 rounded-full bg-text-muted" />
          )}
          {running ? t("projectConductor.threadDock.status.running") : connected ? t("projectConductor.threadDock.status.streaming") : t("projectConductor.threadDock.status.idle")}
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <Input
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void handleStartLoop();
          }}
          placeholder={t("projectConductor.threadDock.promptPlaceholder")}
          className="bg-surface-input border-border-subtle"
        />
        <Button
          data-density={running ? "project-conductor-loop-dispatch-cta" : "project-conductor-loop-cta"}
          onClick={() => void handleStartLoop()}
          disabled={running}
          className={cn("gap-2 shrink-0", running && "motion-essential")}
        >
          {running ? <AgentThinkingIndicator phase="dispatching" size={14} /> : <Play size={14} />}
          {t("projectConductor.threadDock.startLoop")}
        </Button>
      </div>

      {latestResult && (
        <div className="mt-3 rounded-xl border border-brand/15 bg-brand/5 p-3 text-xs leading-relaxed text-text-secondary">
          <span className="font-black text-text-primary">{t("projectConductor.threadDock.latest")}</span> {latestResult.answer}
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-text-muted">
            <Bot size={13} /> {t("projectConductor.threadDock.turns")}
          </div>
          {events.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border-subtle p-3 text-xs text-text-muted">{t("projectConductor.threadDock.empty.turns")}</p>
          ) : (
            events.map((event) => (
              <div key={event.id} className="rounded-xl border border-border-subtle bg-surface-raised/70 p-3 text-xs">
                <div className="font-black text-text-primary">{event.role}</div>
                <p className="mt-1 whitespace-pre-wrap leading-relaxed text-text-secondary">{event.content || t("projectConductor.threadDock.empty.turn")}</p>
              </div>
            ))
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-text-muted">
            <Wrench size={13} /> {t("projectConductor.threadDock.toolCards")}
          </div>
          {tools.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border-subtle p-3 text-xs text-text-muted">{t("projectConductor.threadDock.empty.tools")}</p>
          ) : (
            tools.map((tool, index) => (
              <div
                key={`${tool.id}-${index}`}
                data-density="project-conductor-tool-card"
                className={cn(
                  "relative overflow-hidden rounded-xl border border-border-subtle bg-surface-raised/70 p-3 text-xs transition-colors",
                  isProjectConductorStreaming && index === 0 && !tool.is_error && "motion-essential border-brand/30 bg-brand-muted/10",
                )}
              >
                {isProjectConductorStreaming && index === 0 && !tool.is_error && (
                  <span
                    aria-hidden
                    className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
                  />
                )}
                <div className="flex items-center justify-between gap-2">
                  <span className="font-black text-text-primary">{tool.name}</span>
                  <span className={tool.is_error ? "text-red-500" : "text-text-muted"}>
                    {tool.is_error ? t("projectConductor.threadDock.toolState.error") : t("projectConductor.threadDock.toolState.ok")}
                  </span>
                </div>
                <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-text-muted">
                  {JSON.stringify(tool.result, null, 2)}
                </pre>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
