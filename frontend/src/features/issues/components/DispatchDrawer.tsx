"use client";

import { useState } from "react";
import { Loader2, RotateCcw, Send, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { chatCodexTask, refineCodexTask, rerunCodexTask } from "@/lib/api";
import { SubAgentResultCard } from "./SubAgentResultCard";
import type { DecisionTimelineItem } from "../hooks/useDecisionTimeline";

interface Props {
  item: DecisionTimelineItem | null;
  onClose: () => void;
}

export function DispatchDrawer({ item, onClose }: Props) {
  const { addToast } = useToast();
  const [draft, setDraft] = useState("");
  const [busyAction, setBusyAction] = useState<"chat" | "refine" | "rerun" | null>(null);

  if (!item) return null;

  const runTaskAction = async (action: "chat" | "refine" | "rerun") => {
    if (!item.taskId) return;
    const content = draft.trim();
    if ((action === "chat" || action === "refine") && !content) return;
    setBusyAction(action);
    try {
      if (action === "chat") await chatCodexTask(item.taskId, content);
      if (action === "refine") await refineCodexTask(item.taskId, content);
      if (action === "rerun") await rerunCodexTask(item.taskId);
      if (action !== "rerun") setDraft("");
      addToast({ type: "success", title: `Task ${action} dispatched` });
    } catch (err) {
      addToast({ type: "error", title: `Task ${action} failed`, message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50">
      <button type="button" aria-label="Close dispatch drawer overlay" className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside className="absolute right-0 top-0 flex h-full w-[480px] max-w-[calc(100vw-24px)] flex-col border-l border-border-subtle bg-background shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-border-subtle px-5 py-4">
          <div className="min-w-0">
            <div className="font-mono text-xs font-bold uppercase text-brand">{item.role} · {item.status}</div>
            <h2 className="mt-1 truncate text-lg font-black text-foreground">{item.title}</h2>
            <p className="mt-1 font-mono text-xs text-text-muted">{item.taskId ?? item.toolUseId ?? item.id}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="rounded-xl">
            <X size={16} />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          {item.result ? (
            <SubAgentResultCard result={item.result} />
          ) : (
            <div className="rounded-2xl border border-border-subtle bg-surface-raised p-4 text-sm text-text-muted">
              No SubAgentResult was persisted for this dispatch yet.
            </div>
          )}

          {item.summary && (
            <section className="mt-4 rounded-2xl border border-border-subtle bg-surface-raised p-4">
              <h3 className="mb-2 text-xs font-black uppercase tracking-[0.2em] text-text-muted">Summary</h3>
              <pre className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{item.summary}</pre>
            </section>
          )}

          <section className="mt-4 rounded-2xl border border-border-subtle bg-surface-raised p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted">Task actions</h3>
              <span className="font-mono text-[11px] text-text-muted">{item.taskId ? item.taskId.slice(0, 8) : "no task"}</span>
            </div>
            <textarea
              value={draft}
              disabled={!item.taskId || busyAction != null}
              onChange={(event) => setDraft(event.target.value)}
              rows={4}
              placeholder={item.taskId ? "Chat or refine this dispatched task..." : "This timeline item has no task action target."}
              className="w-full resize-none rounded-xl border border-border-subtle bg-background px-3 py-2 text-xs outline-none placeholder:text-text-muted focus:border-brand/50"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!item.taskId || !draft.trim() || busyAction != null}
                onClick={() => void runTaskAction("chat")}
                className="gap-2 rounded-xl"
              >
                {busyAction === "chat" ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                Chat
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!item.taskId || !draft.trim() || busyAction != null}
                onClick={() => void runTaskAction("refine")}
                className="gap-2 rounded-xl"
              >
                {busyAction === "refine" ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                Refine
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!item.taskId || busyAction != null}
                onClick={() => void runTaskAction("rerun")}
                className="gap-2 rounded-xl"
              >
                {busyAction === "rerun" ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
                Rerun
              </Button>
            </div>
          </section>

          <section className="mt-4 rounded-2xl border border-border-subtle bg-surface-raised p-4">
            <h3 className="mb-2 text-xs font-black uppercase tracking-[0.2em] text-text-muted">Raw conductor turns</h3>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-text-secondary">
              {JSON.stringify(item.rawTurns, null, 2)}
            </pre>
          </section>
        </div>
      </aside>
    </div>
  );
}
