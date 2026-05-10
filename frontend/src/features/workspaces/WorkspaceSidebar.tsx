"use client";

import { useState } from "react";
import type { Workspace } from "@/lib/types";
import { RefreshCw, Plus, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";

interface WorkspaceSidebarProps {
  workspaces: Workspace[];
  currentWorkspaceId: string | null;
  onSelect: (id: string) => void;
  onCreate: (title: string) => void;
  onRefresh: () => void;
  onDelete: (id: string) => void;
  onDeleteAll: () => void;
}

export function WorkspaceSidebar({
  workspaces,
  currentWorkspaceId,
  onSelect,
  onCreate,
  onRefresh,
  onDelete,
  onDeleteAll,
}: WorkspaceSidebarProps) {
  const { addToast } = useToast();
  const [title, setTitle] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null);
  const [deleteAllOpen, setDeleteAllOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setIsDeleting(true); // reuse for create
    try {
      await onCreate(title.trim());
      addToast({ type: "success", title: "Workspace created" });
      setTitle("");
      setShowForm(false);
    } catch (err) {
      addToast({
        type: "error",
        title: "Failed to create workspace",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsDeleting(false);
    }
  }

  function handleDeleteAll(e: React.MouseEvent) {
    e.stopPropagation();
    setDeleteAllOpen(true);
  }

  async function handleDeleteConfirm() {
    setIsDeleting(true);
    try {
      await onDelete(deleteTarget!.id);
      addToast({ type: "success", title: "Workspace deleted" });
    } catch (err) {
      addToast({
        type: "error",
        title: "Failed to delete workspace",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsDeleting(false);
      setDeleteTarget(null);
    }
  }

  async function handleDeleteAllConfirm() {
    setIsDeleting(true);
    try {
      await onDeleteAll();
      addToast({ type: "success", title: "All workspaces deleted" });
    } catch (err) {
      addToast({
        type: "error",
        title: "Failed to delete workspaces",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsDeleting(false);
      setDeleteAllOpen(false);
    }
  }

  return (
    <>
    <aside className="flex flex-col h-full w-64 shrink-0 cc-sidebar">
      <div className="flex items-center justify-between p-5 border-b border-border-subtle">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          {isCollapsed ? (
            <ChevronRight size={14} className="text-text-muted" />
          ) : (
            <ChevronDown size={14} className="text-text-muted" />
          )}
          <h2 className="text-[10px] font-bold uppercase tracking-[0.2em] text-text-muted">Workspaces</h2>
        </button>
        {!isCollapsed && (
          <div className="flex gap-2">
            <button
              onClick={onRefresh}
              className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-foreground transition-colors"
              aria-label="Refresh"
            >
              <RefreshCw size={14} />
            </button>
            <button
              onClick={() => setShowForm(!showForm)}
              className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-foreground transition-colors"
              aria-label="New Workspace"
            >
              <Plus size={14} />
            </button>
          </div>
        )}
      </div>

      {!isCollapsed && (
        <>
          {showForm && (
            <form onSubmit={handleSubmit} className="p-4 border-b border-border-subtle bg-surface/30">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Workspace name"
            autoFocus
            className="w-full px-3 py-2 text-sm rounded-lg cc-input outline-none"
          />
          <div className="flex gap-2 mt-3">
            <button
              type="submit"
              className="flex-1 px-3 py-1.5 text-xs font-bold rounded-lg bg-brand text-background hover:bg-brand/90 transition-all active:scale-[0.98]"
            >
              Create
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="flex-1 px-3 py-1.5 text-xs font-bold rounded-lg border border-border-subtle hover:bg-surface-hover transition-all active:scale-[0.98]"
            >
              Cancel
            </button>
          </div>
        </form>
          )}
        </>
      )}

      <nav className="flex-1 overflow-y-auto p-3 no-scrollbar space-y-1">
        {workspaces.length === 0 && !showForm ? (
          <div className="flex flex-col items-center justify-center h-40 opacity-20">
            <p className="text-[10px] uppercase tracking-widest font-bold">No workspaces found</p>
          </div>
        ) : (
          workspaces.map((ws) => (
            <div
              key={ws.id}
              className={`w-full text-left px-4 py-2.5 rounded-xl text-[13px] transition-all flex items-center justify-between group relative ${
                ws.id === currentWorkspaceId
                  ? "bg-surface-raised text-brand border border-border-strong shadow-sm"
                  : "text-text-secondary hover:bg-surface-hover hover:text-foreground border border-transparent"
              }`}
            >
              <button
                onClick={() => onSelect(ws.id)}
                className="flex-1 truncate font-medium text-left"
              >
                {ws.title}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setDeleteTarget(ws);
                }}
                className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg hover:bg-error/10 text-text-muted hover:text-error transition-all active:scale-90"
                aria-label="Delete workspace"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))
        )}
      </nav>

      {workspaces.length > 0 && (
        <div className="p-4 border-t border-border-subtle">
          <button
            onClick={handleDeleteAll}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 text-[11px] font-bold uppercase tracking-widest text-text-muted hover:text-error hover:bg-error/5 rounded-lg transition-all"
          >
            <Trash2 size={12} />
            Clean all data
          </button>
        </div>
      )}
    </aside>
    <ConfirmDialog
      open={!!deleteTarget}
      onOpenChange={(open) => !open && setDeleteTarget(null)}
      title="Delete Workspace"
      description={deleteTarget ? `Are you sure you want to delete "${deleteTarget.title}"? This action cannot be undone.` : undefined}
      confirmText="Delete"
      onConfirm={handleDeleteConfirm}
      isLoading={isDeleting}
      variant="destructive"
    />
    <ConfirmDialog
      open={deleteAllOpen}
      onOpenChange={setDeleteAllOpen}
      title="Delete All Workspaces"
      description={`Are you sure you want to delete all ${workspaces.length} workspaces? This action cannot be undone.`}
      confirmText="Delete All"
      onConfirm={handleDeleteAllConfirm}
      isLoading={isDeleting}
      variant="destructive"
    />
    </>
  );
}
