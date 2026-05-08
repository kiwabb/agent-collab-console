"use client";

import type { Workspace } from "@/lib/types";
import { Folder, ChevronRight, Clock, Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface WorkspaceGridProps {
  workspaces: Workspace[];
  onSelect: (id: string) => void;
  onCreate: (title: string) => void;
  onDelete: (id: string) => void;
}

export function WorkspaceGrid({
  workspaces,
  onSelect,
  onCreate,
  onDelete,
}: WorkspaceGridProps) {
  const { t } = useI18n();
  const [isCreating, setIsCreating] = (require("react")).useState(false);
  const [newTitle, setNewTitle] = (require("react")).useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newTitle.trim()) {
      onCreate(newTitle.trim());
      setNewTitle("");
      setIsCreating(false);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto w-full animate-in fade-in duration-700">
      <div className="flex items-center justify-between mb-10">
        <div>
          <h2 className="text-3xl font-black tracking-tight text-foreground mb-2">{t("workspace.title")}</h2>
          <p className="text-text-muted font-medium">{t("workspace.subtitle")}</p>
        </div>
        <button
          onClick={() => setIsCreating(true)}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-brand text-background font-bold text-sm shadow-lg shadow-brand/20 hover:scale-[1.02] active:scale-[0.98] transition-all"
        >
          <Plus size={18} />
          {t("workspace.new")}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {isCreating && (
          <form
            onSubmit={handleSubmit}
            className="p-6 rounded-2xl bg-surface-raised border border-brand/50 shadow-2xl animate-in zoom-in duration-300"
          >
            <div className="size-10 rounded-xl bg-brand/10 flex items-center justify-center mb-4">
              <Plus size={20} className="text-brand" />
            </div>
            <input
              autoFocus
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder={t("workspace.namePlaceholder")}
              className="w-full bg-surface-input border border-border-subtle rounded-lg px-4 py-2.5 text-sm outline-none focus:border-brand mb-4"
            />
            <div className="flex gap-2">
              <button
                type="submit"
                className="flex-1 bg-brand text-background text-xs font-bold py-2 rounded-lg"
              >
                {t("workspace.create")}
              </button>
              <button
                type="button"
                onClick={() => setIsCreating(false)}
                className="flex-1 bg-surface-hover text-text-secondary text-xs font-bold py-2 rounded-lg border border-border-subtle"
              >
                {t("workspace.cancel")}
              </button>
            </div>
          </form>
        )}

        {workspaces.map((ws) => (
          <div
            key={ws.id}
            onClick={() => onSelect(ws.id)}
            className="group relative p-6 rounded-2xl bg-surface/40 border border-border-subtle hover:bg-surface-hover hover:border-border-strong hover:shadow-2xl hover:-translate-y-1 transition-all cursor-pointer overflow-hidden"
          >
            <div className="absolute top-0 right-0 p-4 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(ws.id);
                }}
                className="p-2 rounded-lg hover:bg-error/10 text-text-muted hover:text-error transition-all"
              >
                <Trash2 size={14} />
              </button>
            </div>

            <div className="size-12 rounded-2xl bg-surface-raised border border-border-subtle flex items-center justify-center mb-6 shadow-sm group-hover:scale-110 group-hover:bg-brand/5 group-hover:border-brand/20 transition-all">
              <Folder size={24} className="text-text-muted group-hover:text-brand" />
            </div>

            <h3 className="text-[17px] font-black text-foreground mb-2 truncate group-hover:text-brand transition-colors">
              {ws.title}
            </h3>
            
            <div className="flex items-center gap-3 text-text-muted">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest">
                <Clock size={12} />
                <span>{t("workspace.recent")}</span>
              </div>
              <ChevronRight size={14} className="ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all text-brand" />
            </div>
          </div>
        ))}

        {workspaces.length === 0 && !isCreating && (
          <div className="col-span-full py-20 text-center opacity-20 border-2 border-dashed border-border-subtle rounded-3xl">
            <Folder size={48} className="mx-auto mb-4" />
            <p className="text-sm font-black uppercase tracking-widest">{t("workspace.empty")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
