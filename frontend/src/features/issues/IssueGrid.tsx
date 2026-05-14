"use client";

import type { CodexIssue, GitBranch, RuntimeCatalog } from "@/lib/types";
import { getProjectBranches } from "@/lib/api";
import { ListTodo, Plus, ChevronRight, MessageSquare, Trash2, Search, X, Clock } from "lucide-react";
import { useEffect, useMemo, useState, useRef } from "react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { ExecutionConfigSelector, getFallbackConfig, type ExecutionConfigValue } from "@/components/runtime/ExecutionConfigSelector";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const RECENT_SEARCHES_KEY = "agent-collab.recentSearches";
const MAX_RECENT_SEARCHES = 5;

function getRecentSearches(): string[] {
  try {
    const stored = localStorage.getItem(RECENT_SEARCHES_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveRecentSearch(query: string) {
  const current = getRecentSearches();
  const filtered = current.filter((s) => s !== query);
  const updated = [query, ...filtered].slice(0, MAX_RECENT_SEARCHES);
  localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
}

function removeRecentSearch(query: string) {
  const current = getRecentSearches();
  const updated = current.filter((s) => s !== query);
  localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  const mon = Math.floor(day / 30);
  if (mon < 12) return `${mon}mo ago`;
  return `${Math.floor(mon / 12)}y ago`;
}


interface IssueGridProps {
  issues: CodexIssue[];
  onSelect: (id: string) => void;
  onCreate: (
    title: string,
    desc: string,
    executor: "codex" | "claude",
    provider: string | null,
    model: string | null,
    baseBranch?: string | null,
  ) => void;
  onDelete: (id: string) => Promise<void> | void;
  catalog: RuntimeCatalog | null;
  projectId?: string | null;
  projectDefaultBranch?: string | null;
  isLoading?: boolean;
}

export function IssueGrid({ issues, onSelect, onCreate, onDelete, catalog, projectId, projectDefaultBranch, isLoading = false }: IssueGridProps) {
  const { t } = useI18n();
  const [isCreating, setIsCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [recentSearches, setRecentSearches] = useState<string[]>(getRecentSearches);
  const [showSearchDropdown, setShowSearchDropdown] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const defaultExecutionConfig = useMemo<ExecutionConfigValue>(() => getFallbackConfig(
    catalog,
    "codex",
    null,
    null,
  ), [catalog]);
  const [executionConfig, setExecutionConfig] = useState<ExecutionConfigValue>(defaultExecutionConfig);
  const [deleteTarget, setDeleteTarget] = useState<CodexIssue | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [branches, setBranches] = useState<GitBranch[]>([]);
  const [baseBranch, setBaseBranch] = useState<string>(projectDefaultBranch || "");

  // Refresh branch list when the user opens the create form (covers branches
  // created externally since the page loaded).
  useEffect(() => {
    if (!isCreating || !projectId) return;
    getProjectBranches(projectId)
      .then((list) => setBranches(list.filter((b) => !b.is_remote)))
      .catch(() => setBranches([]));
  }, [isCreating, projectId]);

  useEffect(() => {
    if (!baseBranch && projectDefaultBranch) setBaseBranch(projectDefaultBranch);
  }, [projectDefaultBranch, baseBranch]);

  const filteredIssues = useMemo(() => {
    if (!searchQuery.trim()) return issues;
    const query = searchQuery.toLowerCase();
    return issues.filter(
      (issue) =>
        issue.title.toLowerCase().includes(query) ||
        (issue.description && issue.description.toLowerCase().includes(query))
    );
  }, [issues, searchQuery]);

  useEffect(() => {
    setExecutionConfig(defaultExecutionConfig);
  }, [defaultExecutionConfig]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newTitle.trim()) {
      if (searchQuery.trim()) {
        saveRecentSearch(searchQuery.trim());
        setRecentSearches(getRecentSearches());
      }
      const chosenBase = baseBranch || projectDefaultBranch || null;
      onCreate(
        newTitle.trim(),
        newDesc.trim(),
        executionConfig.executor as "codex" | "claude",
        executionConfig.provider,
        executionConfig.model,
        chosenBase,
      );
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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-10 gap-4">
        <div>
          <h2 className="text-3xl font-black tracking-tight text-foreground mb-2">{t("issue.issues")}</h2>
          <p className="text-text-muted font-medium">{t("issue.gridSubtitle")}</p>
        </div>
        <div className="flex items-center gap-3 w-full sm:w-auto">
          <div className="relative flex-1 sm:flex-none">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => setShowSearchDropdown(true)}
              onBlur={() => setTimeout(() => setShowSearchDropdown(false), 200)}
              placeholder="Search issues..."
              className="py-2 w-full sm:w-64 rounded-xl bg-surface-raised border border-border-subtle text-sm outline-none focus:border-brand"
              style={{ paddingLeft: '2.5rem', paddingRight: '2.5rem' }}
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-surface-hover rounded"
              >
                <X size={14} className="text-text-muted" />
              </button>
            )}
            {showSearchDropdown && recentSearches.length > 0 && !searchQuery && (
              <div className="absolute top-full left-0 right-0 mt-2 py-2 rounded-xl bg-surface-raised border border-border-subtle shadow-xl z-50">
                <div className="px-3 py-1 text-[10px] font-black uppercase tracking-widest text-text-muted mb-1">
                  Recent Searches
                </div>
                {recentSearches.map((search) => (
                  <div
                    key={search}
                    onMouseDown={() => {
                      setSearchQuery(search);
                      setShowSearchDropdown(false);
                    }}
                    className="w-full px-3 py-2 flex items-center gap-2 hover:bg-surface-hover text-sm text-left cursor-pointer"
                  >
                    <Clock size={12} className="text-text-muted shrink-0" />
                    <span className="truncate">{search}</span>
                    <button
                      onMouseDown={(e) => {
                        e.stopPropagation();
                        removeRecentSearch(search);
                        setRecentSearches(getRecentSearches());
                      }}
                      className="ml-auto p-1 hover:bg-surface-hover rounded text-text-muted hover:text-error transition-colors"
                    >
                      <X size={10} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={() => setIsCreating(true)}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-brand text-background font-bold text-sm shadow-lg shadow-brand/20 hover:scale-[1.02] active:scale-[0.98] transition-all"
          >
            <Plus size={18} />
            {t("issue.new")}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {isLoading && (
          <>
            {[1, 2, 3].map((i) => (
              <div key={i} className="p-6 rounded-2xl bg-surface/40 border border-border-subtle flex flex-col h-full min-h-[180px]">
                <div className="flex items-start justify-between mb-4">
                  <Skeleton variant="card" className="size-10" />
                  <Skeleton variant="default" className="w-16 h-5" />
                </div>
                <Skeleton variant="text" className="w-3/4 mb-2" />
                <Skeleton variant="text" className="w-1/2 mb-6" />
                <div className="mt-auto">
                  <Skeleton variant="text" className="w-24" />
                </div>
              </div>
            ))}
          </>
        )}

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
            {projectId && (
              <div className="mb-2">
                <label className="block text-[10px] font-black uppercase tracking-[0.2em] text-text-muted mb-2">
                  {t("issue.baseBranch")}
                </label>
                <Select value={baseBranch} onValueChange={(value) => setBaseBranch(value || "")}>
                  <SelectTrigger className="w-full bg-surface-input border-border-subtle font-mono">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {branches.length === 0 && projectDefaultBranch && (
                      <SelectItem value={projectDefaultBranch}>{projectDefaultBranch}</SelectItem>
                    )}
                    {branches.map((b) => {
                      const ago = formatRelativeTime(b.last_commit_date);
                      return (
                        <SelectItem key={b.name} value={b.name}>
                          {b.name}
                          {b.name === projectDefaultBranch ? " (default)" : ""}
                          {ago ? `  · ${ago}` : ""}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="flex gap-2 mt-auto pt-4">
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

        {filteredIssues.map((issue) => (
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

        {filteredIssues.length === 0 && !isCreating && searchQuery && (
          <div className="col-span-full flex flex-col items-center justify-center py-24 px-8 border-2 border-dashed border-border-subtle rounded-3xl bg-surface/20">
            <div className="size-16 rounded-2xl bg-surface-raised border border-border-subtle flex items-center justify-center mb-6 shadow-sm">
              <Search size={32} className="text-text-muted/40" />
            </div>
            <p className="text-sm font-bold text-text-muted mb-6">No results for "{searchQuery}"</p>
            <button
              onClick={() => setSearchQuery("")}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-brand text-background font-bold text-sm shadow-lg shadow-brand/20 hover:bg-brand/90 transition-all"
            >
              Clear Search
            </button>
          </div>
        )}

        {filteredIssues.length === 0 && !isCreating && !searchQuery && (
          <div className="col-span-full flex flex-col items-center justify-center py-24 px-8 border-2 border-dashed border-border-subtle rounded-3xl bg-surface/20">
            <div className="size-16 rounded-2xl bg-surface-raised border border-border-subtle flex items-center justify-center mb-6 shadow-sm">
              <ListTodo size={32} className="text-text-muted/40" />
            </div>
            <p className="text-sm font-bold text-text-muted mb-6">{t("issue.noIssues")}</p>
            <button
              onClick={() => setIsCreating(true)}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-brand text-background font-bold text-sm shadow-lg shadow-brand/20 hover:bg-brand/90 transition-all"
            >
              <Plus size={16} />
              {t("issue.new")}
            </button>
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
