"use client";

import { useState, useCallback, useEffect } from "react";
import type { Workspace } from "@/lib/types";
import { Folder, ChevronRight, Clock, Plus, Trash2, Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";

const FAVORITES_KEY = "agent-collab.favorites";

function getFavorites(): Set<string> {
  try {
    const stored = localStorage.getItem(FAVORITES_KEY);
    return new Set(stored ? JSON.parse(stored) : []);
  } catch {
    return new Set();
  }
}

function saveFavorites(favorites: Set<string>) {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(Array.from(favorites)));
}

interface WorkspaceGridProps {
  workspaces: Workspace[];
  onSelect: (id: string) => void;
  onCreate: (title: string) => void;
  onDelete: (id: string) => void;
  isLoading?: boolean;
}

export function WorkspaceGrid({
  workspaces,
  onSelect,
  onCreate,
  onDelete,
  isLoading = false,
}: WorkspaceGridProps) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [isCreating, setIsCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [favorites, setFavorites] = useState<Set<string>>(getFavorites);
  const [optimisticWorkspaces, setOptimisticWorkspaces] = useState<Workspace[] | null>(null);
  const displayedWorkspaces = [...(optimisticWorkspaces ?? workspaces)].sort((a, b) => {
    const aFav = favorites.has(a.id) ? 0 : 1;
    const bFav = favorites.has(b.id) ? 0 : 1;
    if (aFav !== bFav) return aFav - bFav;
    return (b.last_active_at || "").localeCompare(a.last_active_at || "");
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setIsCreating(true);
    try {
      await onCreate(newTitle.trim());
      addToast({ type: "success", title: "Workspace created" });
      setNewTitle("");
      setIsCreating(false);
    } catch (err) {
      addToast({
        type: "error",
        title: "Failed to create workspace",
        message: err instanceof Error ? err.message : String(err),
      });
      setIsCreating(false);
    }
  };

  const handleDeleteClick = useCallback((ws: Workspace) => {
    setDeleteTarget(ws);
  }, []);

  const toggleFavorite = useCallback((ws: Workspace, e: React.MouseEvent) => {
    e.stopPropagation();
    setFavorites((prev) => {
      const next = new Set(prev);
      if (next.has(ws.id)) {
        next.delete(ws.id);
      } else {
        next.add(ws.id);
      }
      saveFavorites(next);
      return next;
    });
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    
    // Optimistically remove
    setOptimisticWorkspaces((prev) => (prev ?? workspaces).filter((w) => w.id !== deleteTarget.id));
    
    try {
      await onDelete(deleteTarget.id);
      addToast({ type: "success", title: "Workspace deleted" });
      setDeleteTarget(null);
    } catch (err) {
      // Rollback - re-add to optimistic list
      setOptimisticWorkspaces((prev) => [...(prev ?? workspaces), deleteTarget]);
      addToast({
        type: "error",
        title: "Failed to delete workspace",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsDeleting(false);
    }
  }, [deleteTarget, onDelete, addToast]);

  return (
    <div className="p-8 max-w-7xl mx-auto w-full">
      <div className="flex items-center justify-between mb-10">
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5 }}
        >
          <h2 className="text-3xl font-black tracking-tight text-foreground mb-2">{t("workspace.title")}</h2>
          <p className="text-text-muted font-medium">{t("workspace.subtitle")}</p>
        </motion.div>
        <motion.button
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          onClick={() => setIsCreating(true)}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-brand text-background font-bold text-sm shadow-lg shadow-brand/20 transition-all"
        >
          <Plus size={18} />
          {t("workspace.new")}
        </motion.button>
      </div>

      <motion.div 
        layout
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6"
      >
        <AnimatePresence mode="popLayout">
          {isLoading && (
            <>
              {[1, 2, 3, 4].map((i) => (
                <motion.div 
                  key={`skeleton-${i}`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="p-6 rounded-2xl bg-surface/40 border border-border-subtle overflow-hidden"
                >
                  <div className="flex items-start justify-between mb-6">
                    <Skeleton variant="circle" className="size-12" />
                  </div>
                  <Skeleton variant="text" className="w-3/4 mb-2" />
                  <Skeleton variant="text" className="w-1/3" />
                </motion.div>
              ))}
            </>
          )}

          {isCreating && (
            <motion.form
              key="create-form"
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              onSubmit={handleSubmit}
              className="p-6 rounded-2xl bg-surface-raised border border-brand/50 shadow-2xl z-10"
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
                className="w-full bg-surface-input border border-border-subtle rounded-lg px-4 py-2.5 text-sm outline-none focus:border-brand mb-4 transition-colors"
              />
              <div className="flex gap-2">
                <Button
                  type="submit"
                  disabled={isCreating}
                  className="flex-1"
                >
                  {isCreating && (
                    <div className="flex gap-1 mr-2">
                      <div className="size-1 bg-current rounded-full animate-bounce [animation-delay:-0.3s]" />
                      <div className="size-1 bg-current rounded-full animate-bounce [animation-delay:-0.15s]" />
                      <div className="size-1 bg-current rounded-full animate-bounce" />
                    </div>
                  )}
                  {t("workspace.create")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setIsCreating(false)}
                  disabled={isCreating}
                  className="flex-1"
                >
                  {t("workspace.cancel")}
                </Button>
              </div>
            </motion.form>
          )}

          {displayedWorkspaces.map((ws, index) => (
            <motion.div
              key={ws.id}
              layout
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: index * 0.05 }}
              onClick={() => onSelect(ws.id)}
              className="group relative p-6 rounded-2xl bg-surface/40 border border-border-subtle hover:bg-surface-hover hover:border-border-strong hover:shadow-2xl transition-all cursor-pointer overflow-hidden"
            >
              <div className="absolute top-0 right-0 p-4 flex gap-1 opacity-0 group-hover:opacity-100 transition-all z-10">
                <button
                  onClick={(e) => toggleFavorite(ws, e)}
                  className={cn(
                    "p-2 rounded-lg hover:bg-surface-hover transition-all",
                    favorites.has(ws.id) ? "text-warning" : "text-text-muted hover:text-warning"
                  )}
                >
                  <Star size={14} className={favorites.has(ws.id) ? "fill-warning" : ""} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteClick(ws);
                  }}
                  className="p-2 rounded-lg hover:bg-error/10 text-text-muted hover:text-error transition-all"
                >
                  <Trash2 size={14} />
                </button>
              </div>

              <div className="size-12 rounded-2xl bg-surface-raised border border-border-subtle flex items-center justify-center mb-6 shadow-sm group-hover:scale-110 group-hover:bg-brand/5 group-hover:border-brand/20 transition-all">
                {favorites.has(ws.id) ? (
                  <Star size={24} className="text-warning fill-warning" />
                ) : (
                  <Folder size={24} className="text-text-muted group-hover:text-brand" />
                )}
              </div>

              <h3 className="text-[17px] font-black text-foreground mb-2 truncate group-hover:text-brand transition-colors">
                {ws.title}
              </h3>
              {ws.cwd && (
                <div className="text-[10px] font-mono text-text-muted/60 mb-3 truncate" title={ws.cwd}>
                  {ws.cwd}
                </div>
              )}
              <div className="flex items-center gap-3 text-text-muted">
                <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest group-hover:text-text-primary transition-colors">
                  <Clock size={12} />
                  <span>{t("workspace.recent")}</span>
                </div>
                <ChevronRight size={14} className="ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all text-brand" />
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {displayedWorkspaces.length === 0 && !isCreating && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="col-span-full"
          >
            <EmptyState
              icon="workspace"
              title={t("workspace.empty")}
              description="Create your first workspace to get started"
              action={
                <Button
                  onClick={() => setIsCreating(true)}
                  className="flex items-center gap-2 px-6"
                >
                  <Plus size={16} />
                  {t("workspace.new")}
                </Button>
              }
              className="col-span-full py-24 px-8 border-2 border-dashed border-border-subtle rounded-3xl bg-surface/20"
            />
          </motion.div>
        )}
      </motion.div>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={t("workspace.delete")}
        description={deleteTarget ? `Are you sure you want to delete "${deleteTarget.title}"? This action cannot be undone.` : undefined}
        confirmText={t("workspace.delete")}
        onConfirm={handleDeleteConfirm}
        isLoading={isDeleting}
        variant="destructive"
      />
    </div>
  );
}
