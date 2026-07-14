"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BrainCircuit, DatabaseZap, MessageSquareText, RefreshCcw, Send } from "lucide-react";

import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import {
  askProjectConductor,
  getProjectConductorState,
  scheduleProjectConductorReview,
} from "@/lib/api/projects";
import type { ProjectConductorState } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ProjectConductorThreadDock } from "@/features/projects/components/ProjectConductorThreadDock";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";

export function ProjectConductorPage({ projectId }: { projectId: string }) {
  const { addToast } = useToast();
  const { t } = useI18n();
  const [state, setState] = useState<ProjectConductorState | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setState(await getProjectConductorState(projectId));
    } catch (err) {
      addToast({
        type: "error",
        title: t("projectConductor.toast.loadFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  }, [projectId, addToast, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAsk = useCallback(async () => {
    const text = question.trim();
    if (!text) return;
    setAsking(true);
    try {
      const result = await askProjectConductor(projectId, text);
      setAnswer(result.answer);
      setQuestion("");
      await load();
    } catch (err) {
      addToast({
        type: "error",
        title: t("projectConductor.toast.askFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setAsking(false);
    }
  }, [projectId, question, load, addToast, t]);

  const handleScheduledReview = useCallback(async () => {
    setAsking(true);
    try {
      const result = await scheduleProjectConductorReview(projectId);
      setAnswer(result.answer);
      await load();
    } catch (err) {
      addToast({
        type: "error",
        title: t("projectConductor.toast.reviewFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setAsking(false);
    }
  }, [projectId, load, addToast, t]);

  const latestHot = useMemo(() => state?.hot_thread.slice(-6).reverse() ?? [], [state]);
  const isProjectConductorThinking = asking;

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
      <div className="p-5 border-b border-border-subtle flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "size-11 rounded-2xl bg-brand/15 border border-brand/20 flex items-center justify-center text-brand",
              isProjectConductorThinking && "motion-essential border-brand/35 bg-brand-muted/15",
            )}
          >
            {isProjectConductorThinking ? (
              <AgentThinkingIndicator phase="thinking" size={20} />
            ) : (
              <BrainCircuit size={22} />
            )}
          </div>
          <div>
            <h2 className="text-lg font-black tracking-tight">{t("projectConductor.title")}</h2>
            <p className="text-xs text-text-muted max-w-2xl mt-1">
              {t("projectConductor.subtitle")}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => void load()}
            disabled={loading}
            data-density={
              loading ? "project-conductor-refresh-thinking" : "project-conductor-refresh"
            }
            className={cn("gap-2 rounded-xl", loading && "motion-essential")}
          >
            {loading ? (
              <AgentThinkingIndicator phase="thinking" size={14} />
            ) : (
              <RefreshCcw size={14} />
            )}
            {t("projectConductor.refresh")}
          </Button>
          <Button
            size="sm"
            onClick={() => void handleScheduledReview()}
            disabled={asking}
            className="gap-2 rounded-xl"
          >
            {asking ? (
              <AgentThinkingIndicator phase="thinking" size={14} />
            ) : (
              <DatabaseZap size={14} />
            )}
            {t("projectConductor.scheduleReview")}
          </Button>
        </div>
      </div>

      <div className="p-5 grid grid-cols-1 xl:grid-cols-[1.15fr_0.85fr] gap-5">
        <div className="space-y-4">
          <div className="grid grid-cols-2 divide-x divide-y divide-border-subtle border-y border-border-subtle bg-surface md:grid-cols-4 md:divide-y-0">
            <Metric label={t("projectConductor.metric.hotTokens")} value={state?.hot_tokens ?? 0} />
            <Metric
              label={t("projectConductor.metric.warmTokens")}
              value={state?.warm_tokens ?? 0}
            />
            <Metric
              label={t("projectConductor.metric.coldMemories")}
              value={state?.cold_memories.length ?? 0}
            />
            <Metric
              label={t("projectConductor.metric.tasksHandled")}
              value={state?.total_tasks_handled ?? 0}
            />
          </div>

          <div
            data-density={
              isProjectConductorThinking
                ? "project-conductor-thinking-actions"
                : "project-conductor-actions"
            }
            className={cn(
              "relative overflow-hidden border-y border-border-subtle bg-surface py-4",
              isProjectConductorThinking && "motion-essential border-brand/30 bg-brand-muted/10",
            )}
          >
            {isProjectConductorThinking && (
              <div
                aria-hidden
                className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
              />
            )}
            <div className="flex items-center gap-2 mb-3">
              <MessageSquareText size={15} className="text-brand" />
              <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted">
                {t("projectConductor.askTitle")}
              </h3>
            </div>
            <div className="flex gap-2">
              <Input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void handleAsk();
                }}
                placeholder={t("projectConductor.askPlaceholder")}
                className="bg-surface-input border-border-subtle"
              />
              <Button
                onClick={() => void handleAsk()}
                disabled={asking || !question.trim()}
                className="gap-2"
              >
                {asking ? (
                  <AgentThinkingIndicator phase="thinking" size={14} />
                ) : (
                  <Send size={14} />
                )}
                {t("projectConductor.askAction")}
              </Button>
            </div>
            {answer && (
              <pre className="mt-4 whitespace-pre-wrap rounded-2xl border border-brand/15 bg-brand/5 p-4 text-xs leading-relaxed text-text-secondary">
                {answer}
              </pre>
            )}
          </div>

          <MemoryBlock
            title={t("projectConductor.section.pinned")}
            body={state?.pinned_text || t("projectConductor.empty.pinned")}
          />
          <ProjectConductorThreadDock projectId={projectId} onLoopDone={() => void load()} />
        </div>

        <div className="space-y-4">
          <ListBlock
            title={t("projectConductor.section.warmSummaries")}
            empty={t("projectConductor.empty.warm")}
            items={(state?.warm_summaries ?? []).map((item, index) => ({
              id: String(item["id"] ?? index),
              body: String(item["summary"] ?? JSON.stringify(item)),
            }))}
          />
          <ListBlock
            title={t("projectConductor.section.coldMemory")}
            empty={t("projectConductor.empty.cold")}
            items={(state?.cold_memories ?? []).map((item) => ({
              id: item.id,
              body: item.summary_text,
            }))}
          />
          <ListBlock
            title={t("projectConductor.section.hotThread")}
            empty={loading ? t("projectConductor.loading") : t("projectConductor.empty.hot")}
            items={latestHot.map((item, index) => ({
              id: String(item["task_id"] ?? item["created_at"] ?? index),
              body: `${String(item["role"] ?? "event")}: ${String(item["content"] ?? JSON.stringify(item))}`,
            }))}
          />
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0 p-3">
      <div className="text-[10px] uppercase tracking-[0.2em] text-text-muted">{label}</div>
      <div className="mt-1 text-2xl font-black tabular-nums">{value}</div>
    </div>
  );
}

function MemoryBlock({ title, body }: { title: string; body: string }) {
  return (
    <section className="border-y border-border-subtle bg-surface py-4">
      <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted mb-3">
        {title}
      </h3>
      <pre className="max-h-52 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">
        {body}
      </pre>
    </section>
  );
}

function ListBlock({
  title,
  empty,
  items,
}: {
  title: string;
  empty: string;
  items: Array<{ id: string; body: string }>;
}) {
  return (
    <section className="border-y border-border-subtle bg-surface py-4">
      <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted mb-3">
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="text-xs text-text-muted">{empty}</p>
      ) : (
        <ul className="divide-y divide-border-subtle border-y border-border-subtle">
          {items.map((item) => (
            <li key={item.id} className="px-1 py-3 text-xs leading-relaxed text-text-secondary">
              {item.body}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
