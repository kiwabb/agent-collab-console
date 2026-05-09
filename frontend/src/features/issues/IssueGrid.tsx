"use client";

import type { CodexIssue, RuntimeCatalog } from "@/lib/types";
import { ListTodo, Plus, ChevronRight, MessageSquare, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { ExecutionConfigSelector, getFallbackConfig, type ExecutionConfigValue } from "@/components/runtime/ExecutionConfigSelector";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getRuntimeCatalog } from "@/lib/api";

interface IssueGridProps {
  issues: CodexIssue[];
  onSelect: (id: string) => void;
  onCreate: (title: string, desc: string, executor: "codex" | "claude", provider: string | null, model: string | null) => void;
  onDelete: (id: string) => Promise<void> | void;
  catalog: RuntimeCatalog | null;
}

export function IssueGrid({ issues, onSelect, onCreate, onDelete, catalog }: IssueGridProps) {
  const { t } = useI18n();
  const [isCreating, setIsCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const defaultExecutionConfig = useMemo<ExecutionConfigValue>(() => getFallbackConfig(
    catalog,
    "codex",
    null,
    null,
  ), [catalog]);
  const [executionConfig, setExecutionConfig] = useState<ExecutionConfigValue>(defaultExecutionConfig);
  const [deleteTarget, setDeleteTarget] = useState<CodexIssue | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    setExecutionConfig(defaultExecutionConfig);
  }, [defaultExecutionConfig]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newTitle.trim()) {
      onCreate(newTitle.trim(), newDesc.trim(), executionConfig.executor as "codex" | "claude", executionConfig.provider, executionConfig.model);
      setNewTitle("");
      setNewDesc("");
      setExecutionConfig(defaultExecutionConfig);
      setIsCreating(false);
    }
  };

  async function handleDeleteIssue() {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await onDelete(deleteTarget.id);
      setDeleteTarget(null);
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto w-full animate-in fade-in duration-700">
      <div className="flex items-center justify-between mb-10">
        <div>
          <h2 className="text-3xl font-black tracking-tight text-foreground mb-2">{t("issue.issues")}</h2>
          <p className="text-text-muted font-medium">{t("issue.gridSubtitle")}</p>
        </div>
        <button
          onClick={() => setIsCreating(true)}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-brand text-background font-bold text-sm shadow-lg shadow-brand/20 hover:scale-[1.02] active:scale-[0.98] transition-all"
        >
          <Plus size={18} />
          {t("issue.new")}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {isCreating && (
          <form
            onSubmit={handleSubmit}
            className="p-6 rounded-2xl bg-surface-raised border border-brand/50 shadow-2xl animate-in zoom-in duration-300 flex flex-col h-full"
          >
            <div className="size-10 rounded-xl bg-brand/10 flex items-center justify-center mb-4">
              <ListTodo size={20} className="text-brand" />
            </div>
            <input
              autoFocus
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder={t("issue.titlePlaceholder")}
              className="w-full bg-surface-input border border-border-subtle rounded-lg px-4 py-2.5 text-sm outline-none focus:border-brand mb-3"
            />
            <textarea
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder={t("issue.descriptionOptional")}
              rows={3}
              className="w-full bg-surface-input border border-border-subtle rounded-lg px-4 py-2.5 text-sm outline-none focus:border-brand mb-5 resize-none flex-1"
            />
            <div className="mb-5">
              <label className="block text-[10px] font-black uppercase tracking-[0.2em] text-text-muted mb-2">
                {t("task.executor")}
              </label>
              <ExecutionConfigSelector
                value={executionConfig}
                onChange={setExecutionConfig}
                catalog={catalog}
              />
            </div>
            <div className="flex gap-2">
              <button
                type="submit"
                className="flex-1 bg-brand text-background text-xs font-bold py-2.5 rounded-lg"
              >
                {t("issue.create")}
              </button>
              <button
                type="button"
                onClick={() => setIsCreating(false)}
                className="flex-1 bg-surface-hover text-text-secondary text-xs font-bold py-2.5 rounded-lg border border-border-subtle"
              >
                {t("issue.cancel")}
              </button>
            </div>
          </form>
        )}

        {issues.map((issue) => (
          <div
            key={issue.id}
            onClick={() => onSelect(issue.id)}
            className="group p-6 rounded-2xl bg-surface/40 border border-border-subtle hover:bg-surface-hover hover:border-brand/30 hover:shadow-2xl transition-all cursor-pointer flex flex-col h-full min-h-[180px]"
          >
            <div className="flex items-start justify-between mb-4">
              <div className="size-10 rounded-xl bg-surface-raised border border-border-subtle flex items-center justify-center group-hover:bg-brand/5 group-hover:border-brand/20 transition-all">
                <MessageSquare size={18} className="text-text-muted group-hover:text-brand" />
              </div>
              <div className="flex items-center gap-2">
                <div className={cn(
                  "px-2 py-1 rounded-md text-[9px] font-black uppercase tracking-widest border",
                  issue.current_phase === "completed"
                    ? "bg-success/10 text-success border-success/20"
                    : "bg-brand/10 text-brand border-brand/20"
                )}>
                  {issue.current_phase.replace("_", " ")}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  className="text-text-muted hover:text-error hover:bg-error/10 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteTarget(issue);
                  }}
                  title={t("issue.delete")}
                  aria-label={t("issue.delete")}
                >
                  <Trash2 size={12} />
                </Button>
              </div>
            </div>

            <h3 className="text-[16px] font-bold text-foreground mb-2 line-clamp-2 group-hover:text-brand transition-colors">
              {issue.title}
            </h3>
            
            {issue.description && (
              <p className="text-[12px] text-text-secondary line-clamp-2 mb-6 opacity-80 leading-relaxed">
                {issue.description}
              </p>
            )}

            <div className="mt-auto flex items-center gap-4 text-[10px] font-black uppercase tracking-widest text-text-muted">
              <div className="flex items-center gap-1.5">
                <div className="size-1 rounded-full bg-brand/30" />
                <span>Issue ID: {issue.id.slice(0, 8)}</span>
              </div>
              <ChevronRight size={14} className="ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all text-brand" />
            </div>
          </div>
        ))}

        {issues.length === 0 && !isCreating && (
          <div className="col-span-full py-20 text-center opacity-20 border-2 border-dashed border-border-subtle rounded-3xl">
            <ListTodo size={48} className="mx-auto mb-4" />
            <p className="text-sm font-black uppercase tracking-widest">{t("issue.noIssues")}</p>
          </div>
        )}
      </div>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-md" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("issue.delete")}</DialogTitle>
            <DialogDescription className="space-y-3">
              <p>{t("issue.deleteConfirmBody")}</p>
              {deleteTarget && <p className="text-foreground font-semibold">{deleteTarget.title}</p>}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="sm:justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteTarget(null)}
              disabled={isDeleting}
            >
              {t("issue.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDeleteIssue}
              disabled={isDeleting}
            >
              {isDeleting ? t("issue.deleting") : t("issue.deleteConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
