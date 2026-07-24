"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Archive,
  BrainCircuit,
  DatabaseZap,
  History,
  MessageSquareText,
  Pin,
  RefreshCcw,
  Send,
} from "lucide-react";

import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { EmptyStateAction, InteractionEmptyState } from "@/components/ui/interaction-empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ProjectConductorExpandableText } from "@/features/projects/components/ProjectConductorExpandableText";
import { ProjectConductorMemorySection } from "@/features/projects/components/ProjectConductorMemorySection";
import { ProjectConductorThreadDock } from "@/features/projects/components/ProjectConductorThreadDock";
import { projectConductorHotEventBody } from "@/features/projects/projectConductorPresentation";
import {
  askProjectConductor,
  getProjectConductorState,
  scheduleProjectConductorReview,
} from "@/lib/api/projects";
import type { ProjectConductorState } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

function visibleError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function memorySummary(item: Record<string, unknown>): string {
  const summary = item["summary"];
  return typeof summary === "string" ? summary : JSON.stringify(item);
}

export function ProjectConductorPage({ projectId }: { projectId: string }) {
  const { addToast } = useToast();
  const { locale, t } = useI18n();
  const [state, setState] = useState<ProjectConductorState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ projectId: string; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const loadRequestRef = useRef(0);
  const actionRequestRef = useRef(0);
  const activeProjectRef = useRef(projectId);
  activeProjectRef.current = projectId;

  const load = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    const requestedProjectId = projectId;
    setLoading(true);
    setLoadError(null);
    try {
      const nextState = await getProjectConductorState(requestedProjectId);
      if (loadRequestRef.current !== requestId || activeProjectRef.current !== requestedProjectId) {
        return;
      }
      setState(nextState);
    } catch (error) {
      if (loadRequestRef.current !== requestId || activeProjectRef.current !== requestedProjectId) {
        return;
      }
      const message = visibleError(error);
      setLoadError(message);
      addToast({
        type: "error",
        title: t("projectConductor.toast.loadFailed"),
        message,
      });
    } finally {
      if (loadRequestRef.current === requestId && activeProjectRef.current === requestedProjectId) {
        setLoading(false);
      }
    }
  }, [projectId, addToast, t]);

  useEffect(() => {
    actionRequestRef.current += 1;
    setAnswer(null);
    setQuestion("");
    setAsking(false);
    void load();
    return () => {
      loadRequestRef.current += 1;
      actionRequestRef.current += 1;
    };
  }, [load]);

  const handleLoopDone = useCallback(
    (completedProjectId: string) => {
      if (activeProjectRef.current !== completedProjectId) return;
      void load();
    },
    [load],
  );

  const handleAsk = useCallback(async () => {
    const text = question.trim();
    if (!text) return;
    const requestId = ++actionRequestRef.current;
    const requestedProjectId = projectId;
    setAsking(true);
    try {
      const result = await askProjectConductor(requestedProjectId, text);
      if (
        actionRequestRef.current !== requestId ||
        activeProjectRef.current !== requestedProjectId
      ) {
        return;
      }
      setAnswer({ projectId: requestedProjectId, text: result.answer });
      setQuestion("");
      await load();
    } catch (error) {
      if (
        actionRequestRef.current !== requestId ||
        activeProjectRef.current !== requestedProjectId
      ) {
        return;
      }
      addToast({
        type: "error",
        title: t("projectConductor.toast.askFailed"),
        message: visibleError(error),
      });
    } finally {
      if (
        actionRequestRef.current === requestId &&
        activeProjectRef.current === requestedProjectId
      ) {
        setAsking(false);
      }
    }
  }, [projectId, question, load, addToast, t]);

  const handleScheduledReview = useCallback(async () => {
    const requestId = ++actionRequestRef.current;
    const requestedProjectId = projectId;
    setAsking(true);
    try {
      const result = await scheduleProjectConductorReview(requestedProjectId);
      if (
        actionRequestRef.current !== requestId ||
        activeProjectRef.current !== requestedProjectId
      ) {
        return;
      }
      setAnswer({ projectId: requestedProjectId, text: result.answer });
      await load();
    } catch (error) {
      if (
        actionRequestRef.current !== requestId ||
        activeProjectRef.current !== requestedProjectId
      ) {
        return;
      }
      addToast({
        type: "error",
        title: t("projectConductor.toast.reviewFailed"),
        message: visibleError(error),
      });
    } finally {
      if (
        actionRequestRef.current === requestId &&
        activeProjectRef.current === requestedProjectId
      ) {
        setAsking(false);
      }
    }
  }, [projectId, load, addToast, t]);

  const currentState = state?.project_id === projectId ? state : null;
  const currentAnswer = answer?.projectId === projectId ? answer.text : null;
  const latestHot = useMemo(
    () => (currentState ? [...currentState.hot_thread].reverse() : []),
    [currentState],
  );
  const isProjectConductorThinking = asking;
  const updatedAt = currentState?.updated_at
    ? new Date(currentState.updated_at).toLocaleString(locale)
    : t("projectConductor.updated.never");

  return (
    <section
      data-density={
        isProjectConductorThinking ? "project-conductor-thinking-shell" : "project-conductor-shell"
      }
      className={cn(
        "relative overflow-hidden border-y border-border-subtle bg-background",
        isProjectConductorThinking && "motion-essential border-brand/35",
      )}
    >
      {isProjectConductorThinking && (
        <div
          aria-hidden
          className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
        />
      )}

      <header className="flex flex-col gap-4 border-b border-border-subtle px-4 py-5 sm:px-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={cn(
              "flex size-11 shrink-0 items-center justify-center border border-brand/20 bg-brand/10 text-brand",
              isProjectConductorThinking && "motion-essential border-brand/35 bg-brand-muted/15",
            )}
          >
            {isProjectConductorThinking ? (
              <AgentThinkingIndicator phase="thinking" size={20} />
            ) : (
              <BrainCircuit size={21} aria-hidden />
            )}
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-black tracking-tight text-foreground">
              {t("projectConductor.title")}
            </h1>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-text-muted">
              {t("projectConductor.subtitle")}
            </p>
            {currentState && (
              <p className="mt-2 text-[11px] text-text-muted">
                {t("projectConductor.updated.label", { time: updatedAt })}
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => void load()}
            disabled={loading}
            data-density={
              loading ? "project-conductor-refresh-thinking" : "project-conductor-refresh"
            }
            className={cn("min-h-10 gap-2", loading && "motion-essential")}
          >
            {loading ? (
              <AgentThinkingIndicator phase="thinking" size={14} />
            ) : (
              <RefreshCcw size={14} aria-hidden />
            )}
            {t("projectConductor.refresh")}
          </Button>
          <Button
            size="sm"
            onClick={() => void handleScheduledReview()}
            disabled={asking || !currentState}
            className="min-h-10 gap-2"
          >
            {asking ? (
              <AgentThinkingIndicator phase="thinking" size={14} />
            ) : (
              <DatabaseZap size={14} aria-hidden />
            )}
            {t("projectConductor.scheduleReview")}
          </Button>
        </div>
      </header>

      <div className="space-y-5 px-4 py-5 sm:px-6">
        {loading && !currentState ? (
          <InteractionEmptyState
            tone="loading"
            title={t("projectConductor.loading.title")}
            description={t("projectConductor.loading.description")}
          />
        ) : loadError && !currentState ? (
          <div role="alert">
            <InteractionEmptyState
              tone="error"
              title={t("projectConductor.error.title")}
              description={
                <>
                  {t("projectConductor.error.description")}
                  <span className="mt-2 block font-mono text-[11px]">{loadError}</span>
                </>
              }
              action={
                <EmptyStateAction onClick={() => void load()} className="min-h-10 gap-2">
                  <RefreshCcw size={14} aria-hidden />
                  {t("projectConductor.error.retry")}
                </EmptyStateAction>
              }
            />
          </div>
        ) : currentState ? (
          <>
            {loadError && (
              <div
                role="alert"
                className="flex flex-col gap-3 border-y border-status-failed/35 bg-status-failed/5 px-4 py-3 text-sm text-status-failed sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex min-w-0 items-start gap-2">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
                  <div className="min-w-0">
                    <div className="font-semibold">{t("projectConductor.error.staleTitle")}</div>
                    <div className="mt-1 break-words text-xs opacity-90">{loadError}</div>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => void load()} className="gap-2">
                  <RefreshCcw size={14} aria-hidden />
                  {t("projectConductor.error.retry")}
                </Button>
              </div>
            )}

            <div className="grid grid-cols-2 divide-x divide-y divide-border-subtle border-y border-border-subtle bg-surface md:grid-cols-4 md:divide-y-0">
              <Metric
                label={t("projectConductor.metric.hotTokens")}
                value={currentState.hot_tokens}
              />
              <Metric
                label={t("projectConductor.metric.warmTokens")}
                value={currentState.warm_tokens}
              />
              <Metric
                label={t("projectConductor.metric.coldMemories")}
                value={currentState.cold_memories_total}
              />
              <Metric
                label={t("projectConductor.metric.tasksHandled")}
                value={currentState.total_tasks_handled}
              />
            </div>

            <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.7fr)_minmax(280px,0.8fr)]">
              <section
                data-density={
                  isProjectConductorThinking
                    ? "project-conductor-thinking-actions"
                    : "project-conductor-actions"
                }
                className={cn(
                  "relative overflow-hidden border-y border-border-subtle bg-surface px-4 py-5",
                  isProjectConductorThinking &&
                    "motion-essential border-brand/30 bg-brand-muted/10",
                )}
              >
                {isProjectConductorThinking && (
                  <div
                    aria-hidden
                    className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
                  />
                )}
                <div className="flex items-center gap-2">
                  <MessageSquareText size={16} className="text-brand" aria-hidden />
                  <h2 className="text-sm font-bold text-foreground">
                    {t("projectConductor.askTitle")}
                  </h2>
                </div>
                <p className="mt-1 text-xs leading-5 text-text-muted">
                  {t("projectConductor.askDescription")}
                </p>
                <label
                  htmlFor="project-conductor-question"
                  className="mt-4 block text-xs font-semibold text-text-secondary"
                >
                  {t("projectConductor.askLabel")}
                </label>
                <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                  <Input
                    id="project-conductor-question"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void handleAsk();
                    }}
                    placeholder={t("projectConductor.askPlaceholder")}
                    className="min-h-11 border-border-subtle bg-surface-input"
                  />
                  <Button
                    onClick={() => void handleAsk()}
                    disabled={asking || !question.trim()}
                    className="min-h-11 shrink-0 gap-2"
                  >
                    {asking ? (
                      <AgentThinkingIndicator phase="thinking" size={14} />
                    ) : (
                      <Send size={14} aria-hidden />
                    )}
                    {t("projectConductor.askAction")}
                  </Button>
                </div>
                {currentAnswer && (
                  <div className="mt-4 border-l-2 border-brand bg-brand/5 px-4 py-3">
                    <div className="mb-2 text-[10px] font-black uppercase tracking-[0.16em] text-brand">
                      {t("projectConductor.answer.latest")}
                    </div>
                    <ProjectConductorExpandableText text={currentAnswer} />
                  </div>
                )}
              </section>

              <ProjectConductorMemorySection
                title={t("projectConductor.section.pinned")}
                description={t("projectConductor.section.pinnedDescription")}
                empty={t("projectConductor.empty.pinned")}
                icon={Pin}
                items={
                  currentState.pinned_text
                    ? [{ id: "pinned-project-memory", body: currentState.pinned_text }]
                    : []
                }
              />
            </div>

            <div>
              <div className="mb-3 flex items-start gap-2">
                <History size={16} className="mt-0.5 text-brand" aria-hidden />
                <div>
                  <h2 className="text-sm font-bold text-foreground">
                    {t("projectConductor.memory.title")}
                  </h2>
                  <p className="mt-1 text-xs leading-5 text-text-muted">
                    {t("projectConductor.memory.description")}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <ProjectConductorMemorySection
                  title={t("projectConductor.section.hotThread")}
                  description={t("projectConductor.section.hotDescription")}
                  empty={t("projectConductor.empty.hot")}
                  icon={Activity}
                  truncated={currentState.hot_thread_truncated}
                  items={latestHot.map((item, index) => ({
                    id: String(item["task_id"] ?? item["created_at"] ?? `hot-${index}`),
                    body: projectConductorHotEventBody(item),
                    meta: typeof item["kind"] === "string" ? item["kind"] : undefined,
                  }))}
                />
                <ProjectConductorMemorySection
                  title={t("projectConductor.section.warmSummaries")}
                  description={t("projectConductor.section.warmDescription")}
                  empty={t("projectConductor.empty.warm")}
                  icon={Archive}
                  truncated={currentState.warm_summaries_truncated}
                  items={currentState.warm_summaries.map((item, index) => ({
                    id: String(item["id"] ?? `warm-${index}`),
                    body: memorySummary(item),
                  }))}
                />
                <ProjectConductorMemorySection
                  title={t("projectConductor.section.coldMemory")}
                  description={t("projectConductor.section.coldDescription")}
                  empty={t("projectConductor.empty.cold")}
                  icon={DatabaseZap}
                  truncated={currentState.cold_memories_truncated}
                  items={currentState.cold_memories.map((item) => ({
                    id: item.id,
                    body: item.summary_text,
                    meta: item.source_kind,
                  }))}
                />
              </div>
            </div>

            <ProjectConductorThreadDock
              key={projectId}
              projectId={projectId}
              onLoopDone={handleLoopDone}
            />
          </>
        ) : null}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-text-muted">
        {label}
      </div>
      <div className="mt-1 text-2xl font-black tabular-nums text-foreground">
        {value.toLocaleString()}
      </div>
    </div>
  );
}
