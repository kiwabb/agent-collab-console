"use client";

import { useState, useMemo } from "react";
import type { CodexIssue, CodexTask } from "@/lib/types";
import { IssueCard } from "./IssueCard";
import { SortableIssueCard } from "./SortableIssueCard";
import { PHASES, type Phase, groupIssuesByPhase } from "./phaseUtils";
import { Plus, Layout } from "lucide-react";
import { useI18n } from "@/providers/I18nProvider";
import type { TranslationKey } from "@/lib/i18n";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";

interface IssueBoardProps {
  issues: CodexIssue[];
  tasks: CodexTask[];
  currentIssueId: string | null;
  onSelectIssue: (id: string) => void;
  onCreateIssue: (title: string, description: string) => void;
  onReorderIssues?: (activeId: string, overId: string) => void;
  onUpdateIssue?: (id: string, updates: { title?: string; description?: string }) => void;
}

export function IssueBoard({
  issues,
  tasks,
  currentIssueId,
  onSelectIssue,
  onCreateIssue,
  onReorderIssues,
  onUpdateIssue,
}: IssueBoardProps) {
  const { t } = useI18n();
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [showForm, setShowForm] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const byPhase = useMemo(() => groupIssuesByPhase(issues), [issues]);

  const getTaskCounts = useMemo(() => (issueId: string) => {
    const issueTasks = tasks.filter((t) => t.issue_id === issueId);
    return {
      total: issueTasks.length,
      running: issueTasks.filter((t) => t.status === "running" || t.status === "responding").length,
      failed: issueTasks.filter((t) => t.status === "failed").length,
      waiting: issueTasks.filter((t) => t.status === "waiting" || t.status === "blocked").length,
    };
  }, [tasks]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    onCreateIssue(newTitle.trim(), newDesc.trim());
    setNewTitle("");
    setNewDesc("");
    setShowForm(false);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (over && active.id !== over.id && onReorderIssues) {
      onReorderIssues(active.id as string, over.id as string);
    }
  }

  const boardPhases: { id: Phase; labelKey: string; color: string }[] = [
    { id: "requirements", labelKey: "phase.requirements", color: "bg-text-muted" },
    { id: "architecture", labelKey: "phase.architecture", color: "bg-warning" },
    { id: "development", labelKey: "phase.development", color: "bg-brand" },
    { id: "testing", labelKey: "phase.testing", color: "bg-success" },
  ];

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      {/* Board Header */}
      <div className="flex items-center justify-between p-6 border-b border-border-subtle bg-surface/50" data-tour="workspace">
        <div className="flex items-center gap-4">
          <div className="size-8 rounded-xl bg-surface-raised border border-border-subtle flex items-center justify-center">
            <Layout size={18} className="text-brand" />
          </div>
          <div>
            <h2 className="text-lg font-black tracking-tighter text-foreground">{t("issue.boardTitle")}</h2>
            <p className="text-[10px] uppercase tracking-[0.2em] font-bold text-text-muted">{t("issue.boardSubtitle")}</p>
          </div>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 px-5 py-2 rounded-xl bg-brand text-background hover:scale-[1.02] active:scale-[0.98] transition-all font-bold text-sm shadow-lg shadow-brand/20"
          data-tour="issue-create"
        >
          <Plus size={16} />
          {t("issue.create")}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="p-8 border-b border-border-subtle bg-surface-raised/30 animate-in slide-in-from-top-4 duration-500">
          <div className="max-w-2xl">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder={t("issue.titlePlaceholder")}
              autoFocus
              className="w-full px-5 py-3 text-sm rounded-xl cc-input outline-none mb-4 font-bold shadow-inner"
            />
            <textarea
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder={t("issue.descriptionPlaceholder")}
              rows={3}
              className="w-full px-5 py-3 text-sm rounded-xl cc-input outline-none mb-6 resize-none shadow-inner"
            />
            <div className="flex gap-3">
              <button
                type="submit"
                className="px-6 py-2.5 text-xs font-black uppercase tracking-widest rounded-lg bg-brand text-background hover:bg-brand/90 transition-all shadow-md"
              >
                {t("issue.confirm")}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-6 py-2.5 text-xs font-black uppercase tracking-widest rounded-lg border border-border-subtle hover:bg-surface-hover transition-all"
              >
                {t("issue.cancel")}
              </button>
            </div>
          </div>
        </form>
      )}

      {/* Swimlanes */}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <div className="flex-1 overflow-x-auto no-scrollbar bg-surface/5">
          <div className="flex h-full min-w-max p-6 gap-6">
            {boardPhases.map((phase) => {
              const phaseIssues = byPhase[phase.id];
              return (
                <div key={phase.id} className="flex flex-col w-[350px] shrink-0 group/column" data-tour="phases">
                  <div className="flex items-center justify-between mb-6 px-1">
                    <div className="flex items-center gap-3">
                      <div className={`size-2.5 rounded-full ${phase.color} shadow-sm`} />
                      <h3 className="text-[11px] font-black uppercase tracking-[0.25em] text-text-secondary group-hover/column:text-foreground transition-colors">
                        {t(phase.labelKey as TranslationKey)}
                      </h3>
                      <span className="text-[10px] font-black text-text-muted bg-surface-raised px-2.5 py-0.5 rounded-full border border-border-subtle shadow-sm">
                        {phaseIssues.length}
                      </span>
                    </div>
                    <button 
                      onClick={() => {
                        setNewTitle("");
                        setNewDesc("");
                        setShowForm(true);
                      }}
                      className="p-1.5 rounded-lg hover:bg-surface-hover text-text-muted hover:text-brand transition-all opacity-0 group-hover/column:opacity-100"
                    >
                      <Plus size={14} />
                    </button>
                  </div>

                  <SortableContext
                    items={phaseIssues.map(i => i.id)}
                    strategy={verticalListSortingStrategy}
                  >
                    <div className="flex flex-col gap-4 flex-1 overflow-y-auto no-scrollbar pb-20">
                      {phaseIssues.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-20 opacity-[0.03] border-2 border-dashed border-foreground rounded-3xl">
                          <p className="text-[10px] uppercase tracking-widest font-black">{t("issue.ready")}</p>
                        </div>
                      ) : (
                        phaseIssues.map((issue) => {
                          const counts = getTaskCounts(issue.id);
                          return (
                            <div key={issue.id} className="animate-in fade-in slide-in-from-bottom-2 duration-500">
                              <SortableIssueCard
                                issue={issue}
                                isSelected={issue.id === currentIssueId}
                                taskCount={counts.total}
                                runningCount={counts.running}
                                failedCount={counts.failed}
                                waitingCount={counts.waiting}
                                onClick={() => onSelectIssue(issue.id)}
                                onUpdateIssue={onUpdateIssue}
                              />
                            </div>
                          );
                        })
                      )}
                    </div>
                  </SortableContext>
                </div>
              );
            })}
          </div>
        </div>
      </DndContext>
    </div>



  );
}
