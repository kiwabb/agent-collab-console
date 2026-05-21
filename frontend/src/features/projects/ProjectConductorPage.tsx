"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BrainCircuit, DatabaseZap, Loader2, MessageSquareText, RefreshCcw, Send } from "lucide-react";

import {
  askProjectConductor,
  getProjectConductorState,
  scheduleProjectConductorReview,
} from "@/lib/api";
import type { ProjectConductorState } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ProjectConductorThreadDock } from "@/features/projects/components/ProjectConductorThreadDock";

export function ProjectConductorPage({ projectId }: { projectId: string }) {
  const { addToast } = useToast();
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
        title: "Failed to load ProjectConductor",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  }, [projectId, addToast]);

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
        title: "ProjectConductor ask failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setAsking(false);
    }
  }, [projectId, question, load, addToast]);

  const handleScheduledReview = useCallback(async () => {
    setAsking(true);
    try {
      const result = await scheduleProjectConductorReview(projectId);
      setAnswer(result.answer);
      await load();
    } catch (err) {
      addToast({
        type: "error",
        title: "Scheduled review failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setAsking(false);
    }
  }, [projectId, load, addToast]);

  const latestHot = useMemo(() => state?.hot_thread.slice(-6).reverse() ?? [], [state]);

  return (
    <section className="rounded-3xl border border-border-subtle bg-[radial-gradient(circle_at_top_left,rgba(230,149,82,0.18),transparent_34%),linear-gradient(135deg,var(--surface-raised),var(--surface))] overflow-hidden shadow-2xl shadow-black/5">
      <div className="p-5 border-b border-border-subtle flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-3">
          <div className="size-11 rounded-2xl bg-brand/15 border border-brand/20 flex items-center justify-center text-brand">
            <BrainCircuit size={22} />
          </div>
          <div>
            <h2 className="text-lg font-black tracking-tight">ProjectConductor</h2>
            <p className="text-xs text-text-muted max-w-2xl mt-1">
              Long-lived project runtime with hot, warm, cold, and pinned memory.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading} className="gap-2 rounded-xl">
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCcw size={14} />}
            Refresh
          </Button>
          <Button size="sm" onClick={() => void handleScheduledReview()} disabled={asking} className="gap-2 rounded-xl">
            <DatabaseZap size={14} />
            Schedule review
          </Button>
        </div>
      </div>

      <div className="p-5 grid grid-cols-1 xl:grid-cols-[1.15fr_0.85fr] gap-5">
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Metric label="Hot tokens" value={state?.hot_tokens ?? 0} />
            <Metric label="Warm tokens" value={state?.warm_tokens ?? 0} />
            <Metric label="Cold memories" value={state?.cold_memories.length ?? 0} />
            <Metric label="Tasks handled" value={state?.total_tasks_handled ?? 0} />
          </div>

          <div className="rounded-2xl border border-border-subtle bg-surface/65 p-4">
            <div className="flex items-center gap-2 mb-3">
              <MessageSquareText size={15} className="text-brand" />
              <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted">Ask the conductor</h3>
            </div>
            <div className="flex gap-2">
              <Input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void handleAsk();
                }}
                placeholder="What risk should we remember across this project?"
                className="bg-surface-input border-border-subtle"
              />
              <Button onClick={() => void handleAsk()} disabled={asking || !question.trim()} className="gap-2">
                {asking ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                Ask
              </Button>
            </div>
            {answer && (
              <pre className="mt-4 whitespace-pre-wrap rounded-2xl border border-brand/15 bg-brand/5 p-4 text-xs leading-relaxed text-text-secondary">
                {answer}
              </pre>
            )}
          </div>

          <MemoryBlock title="Pinned" body={state?.pinned_text || "No pinned project notes yet."} />
          <ProjectConductorThreadDock projectId={projectId} onLoopDone={() => void load()} />
        </div>

        <div className="space-y-4">
          <ListBlock
            title="Warm Summaries"
            empty="No warm summaries yet."
            items={(state?.warm_summaries ?? []).map((item, index) => ({
              id: String(item.id ?? index),
              body: String(item.summary ?? JSON.stringify(item)),
            }))}
          />
          <ListBlock
            title="Cold Memory"
            empty="No cold memories yet."
            items={(state?.cold_memories ?? []).map((item) => ({
              id: item.id,
              body: item.summary_text,
            }))}
          />
          <ListBlock
            title="Hot Thread"
            empty={loading ? "Loading..." : "No hot events yet."}
            items={latestHot.map((item, index) => ({
              id: String(item.task_id ?? item.created_at ?? index),
              body: `${String(item.role ?? "event")}: ${String(item.content ?? JSON.stringify(item))}`,
            }))}
          />
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-border-subtle bg-surface/70 p-3">
      <div className="text-[10px] uppercase tracking-[0.2em] text-text-muted">{label}</div>
      <div className="mt-1 text-2xl font-black tabular-nums">{value}</div>
    </div>
  );
}

function MemoryBlock({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-border-subtle bg-surface/65 p-4">
      <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted mb-3">{title}</h3>
      <pre className="max-h-52 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">
        {body}
      </pre>
    </div>
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
    <div className="rounded-2xl border border-border-subtle bg-surface/65 p-4">
      <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted mb-3">{title}</h3>
      {items.length === 0 ? (
        <p className="text-xs text-text-muted">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id} className="rounded-xl border border-border-subtle bg-surface-raised/70 p-3 text-xs leading-relaxed text-text-secondary">
              {item.body}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
