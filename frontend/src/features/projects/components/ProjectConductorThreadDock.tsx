"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Bot, Play, RadioTower, Wrench } from "lucide-react";

import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ProjectConductorExpandableText } from "@/features/projects/components/ProjectConductorExpandableText";
import { startProjectConductorLoop } from "@/lib/api/projects";
import type { ProjectConductorLoopResult, ProjectConductorToolEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

type ThreadEvent = {
  id: string;
  role: string;
  content: string;
  status: string;
};

function toolResultText(result: unknown): string {
  const text = JSON.stringify(result, null, 2);
  return text === undefined ? String(result) : text;
}

export function ProjectConductorThreadDock({
  projectId,
  onLoopDone,
}: {
  projectId: string;
  onLoopDone?: (completedProjectId: string) => void;
}) {
  const promptId = useId();
  const { addToast } = useToast();
  const { t } = useI18n();
  const [prompt, setPrompt] = useState("");
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<ThreadEvent[]>([]);
  const [tools, setTools] = useState<ProjectConductorToolEvent[]>([]);
  const [latestResult, setLatestResult] = useState<ProjectConductorLoopResult | null>(null);
  const mountedRef = useRef(false);
  const loopRequestRef = useRef(0);
  const isProjectConductorStreaming = running;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      loopRequestRef.current += 1;
    };
  }, []);

  const handleStartLoop = useCallback(async () => {
    const requestId = ++loopRequestRef.current;
    setRunning(true);
    try {
      const result = await startProjectConductorLoop(projectId, prompt.trim() || undefined);
      if (!mountedRef.current || loopRequestRef.current !== requestId) return;
      setLatestResult(result);
      setEvents((previous) =>
        [
          {
            id: result.task_id,
            role: "project_conductor",
            content: result.answer,
            status: result.status,
          },
          ...previous,
        ].slice(0, 12),
      );
      setTools((previous) => [...result.tool_events, ...previous].slice(0, 12));
      setPrompt("");
      onLoopDone?.(projectId);
    } catch (error) {
      if (!mountedRef.current || loopRequestRef.current !== requestId) return;
      addToast({
        type: "error",
        title: t("projectConductor.toast.loopFailed"),
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      if (mountedRef.current && loopRequestRef.current === requestId) {
        setRunning(false);
      }
    }
  }, [projectId, prompt, onLoopDone, addToast, t]);

  return (
    <section
      data-density="project-conductor-thread-dock"
      className={cn(
        "relative overflow-hidden border-y border-border-subtle bg-surface px-4 py-5",
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
              "flex size-9 shrink-0 items-center justify-center border border-brand/20 bg-brand/10 text-brand",
              isProjectConductorStreaming && "border-brand/35 bg-brand/15",
            )}
          >
            <RadioTower size={17} aria-hidden />
          </div>
          <div>
            <h2 className="text-sm font-bold text-foreground">
              {t("projectConductor.threadDock.title")}
            </h2>
            <p className="mt-1 text-xs leading-5 text-text-muted">
              {t("projectConductor.threadDock.replayHint")}
            </p>
          </div>
        </div>
        <div
          className={cn(
            "flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-muted",
            running && "text-brand",
          )}
        >
          {running ? (
            <AgentThinkingIndicator phase="dispatching" size={14} />
          ) : (
            <span aria-hidden className="size-2 rounded-full bg-text-muted" />
          )}
          {running
            ? t("projectConductor.threadDock.status.running")
            : t("projectConductor.threadDock.status.idle")}
        </div>
      </div>

      <div className="mt-4">
        <label htmlFor={promptId} className="block text-xs font-semibold text-text-secondary">
          {t("projectConductor.threadDock.promptLabel")}
        </label>
        <p id={`${promptId}-description`} className="mt-1 text-xs leading-5 text-text-muted">
          {t("projectConductor.threadDock.promptDescription")}
        </p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <Input
            id={promptId}
            aria-describedby={`${promptId}-description`}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !running) void handleStartLoop();
            }}
            placeholder={t("projectConductor.threadDock.promptPlaceholder")}
            className="min-h-11 border-border-subtle bg-surface-input"
          />
          <Button
            data-density={
              running ? "project-conductor-loop-dispatch-cta" : "project-conductor-loop-cta"
            }
            onClick={() => void handleStartLoop()}
            disabled={running}
            className={cn("min-h-11 shrink-0 gap-2", running && "motion-essential")}
          >
            {running ? (
              <AgentThinkingIndicator phase="dispatching" size={14} />
            ) : (
              <Play size={14} aria-hidden />
            )}
            {t("projectConductor.threadDock.startLoop")}
          </Button>
        </div>
      </div>

      {latestResult && (
        <div className="mt-4 border-l-2 border-brand bg-brand/5 px-4 py-3">
          <div className="mb-2 text-[10px] font-black uppercase tracking-[0.16em] text-brand">
            {t("projectConductor.threadDock.latest")}
          </div>
          <ProjectConductorExpandableText text={latestResult.answer} />
        </div>
      )}

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-bold text-foreground">
            <Bot size={14} className="text-brand" aria-hidden />
            {t("projectConductor.threadDock.turns")}
          </div>
          {events.length === 0 ? (
            <p className="mt-3 border-l-2 border-border-subtle pl-3 text-xs leading-5 text-text-muted">
              {t("projectConductor.threadDock.empty.turns")}
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-border-subtle border-y border-border-subtle">
              {events.map((event) => (
                <li key={event.id} className="py-3">
                  <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-foreground">{event.role}</span>
                    <span className="text-[10px] uppercase tracking-[0.14em] text-text-muted">
                      {event.status}
                    </span>
                  </div>
                  <ProjectConductorExpandableText
                    text={event.content || t("projectConductor.threadDock.empty.turn")}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-bold text-foreground">
            <Wrench size={14} className="text-brand" aria-hidden />
            {t("projectConductor.threadDock.toolCards")}
          </div>
          {tools.length === 0 ? (
            <p className="mt-3 border-l-2 border-border-subtle pl-3 text-xs leading-5 text-text-muted">
              {t("projectConductor.threadDock.empty.tools")}
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-border-subtle border-y border-border-subtle">
              {tools.map((tool, index) => (
                <li
                  key={`${tool.id}-${index}`}
                  data-density="project-conductor-tool-card"
                  className="py-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-xs font-semibold text-foreground">
                      {tool.name}
                    </span>
                    <span
                      className={
                        tool.is_error ? "text-xs text-status-failed" : "text-xs text-text-muted"
                      }
                    >
                      {tool.is_error
                        ? t("projectConductor.threadDock.toolState.error")
                        : t("projectConductor.threadDock.toolState.ok")}
                    </span>
                  </div>
                  <ProjectConductorExpandableText
                    text={toolResultText(tool.result)}
                    mono
                    className="mt-2"
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
