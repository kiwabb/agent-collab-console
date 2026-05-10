"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { cn } from "@/lib/utils";
import {
  Search,
  Bookmark,
  Clock,
  Terminal,
  Plus,
  Home,
  Settings,
  Layout,
  FileText,
  X,
  ArrowRight,
  ChevronRight,
} from "lucide-react";
import { useRouter } from "next/navigation";

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  icon: React.ReactNode;
  action: () => void;
  category: "action" | "bookmark" | "history";
}

interface BookmarkItem {
  id: string;
  label: string;
  type: "issue" | "task" | "workspace";
  icon: React.ReactNode;
  action: () => void;
  addedAt: number;
}

interface HistoryItem {
  id: string;
  label: string;
  description?: string;
  type: string;
  icon: React.ReactNode;
  action: () => void;
  timestamp: number;
}

type Tab = "commands" | "bookmarks" | "history";

const MAX_HISTORY = 50;
const MAX_BOOKMARKS = 20;

export function useBookmarks() {
  const [bookmarks, setBookmarks] = useState<BookmarkItem[]>([]);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("agent-collab.bookmarks");
      if (stored) setBookmarks(JSON.parse(stored));
    } catch {}
  }, []);

  const addBookmark = useCallback((item: Omit<BookmarkItem, "addedAt" | "id">) => {
    setBookmarks((prev) => {
      const exists = prev.some((b) => b.id === item.id);
      if (exists) return prev;
      const next = [{ ...item, id: `bm-${Date.now()}`, addedAt: Date.now() }, ...prev].slice(0, MAX_BOOKMARKS);
      localStorage.setItem("agent-collab.bookmarks", JSON.stringify(next));
      return next;
    });
  }, []);

  const removeBookmark = useCallback((id: string) => {
    setBookmarks((prev) => {
      const next = prev.filter((b) => b.id !== id);
      localStorage.setItem("agent-collab.bookmarks", JSON.stringify(next));
      return next;
    });
  }, []);

  const isBookmarked = useCallback((itemId: string) => {
    return bookmarks.some((b) => b.id === itemId);
  }, [bookmarks]);

  return { bookmarks, addBookmark, removeBookmark, isBookmarked };
}

export function useHistory() {
  const [history, setHistory] = useState<HistoryItem[]>([]);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("agent-collab.history");
      if (stored) setHistory(JSON.parse(stored));
    } catch {}
  }, []);

  const addHistory = useCallback((item: Omit<HistoryItem, "timestamp" | "id">) => {
    setHistory((prev) => {
      const existing = prev.findIndex((h) => h.id === item.id);
      let next: HistoryItem[];
      if (existing >= 0) {
        next = prev.filter((_, i) => i !== existing);
      } else {
        next = prev;
      }
      const final = [{ ...item, id: `${item.id}-${Date.now()}`, timestamp: Date.now() }, ...next].slice(0, MAX_HISTORY);
      localStorage.setItem("agent-collab.history", JSON.stringify(final));
      return final;
    });
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    localStorage.removeItem("agent-collab.history");
  }, []);

  return { history, addHistory, clearHistory };
}

export function CommandPalette({
  onCreateIssue,
  onCreateWorkspace,
  onNavigate,
}: {
  onCreateIssue?: () => void;
  onCreateWorkspace?: () => void;
  onNavigate?: (view: string, id?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("commands");
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const { bookmarks, removeBookmark } = useBookmarks();
  const { history, clearHistory } = useHistory();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setTab("commands");
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const commands: CommandItem[] = useMemo(() => [
    {
      id: "new-issue",
      label: "Create New Issue",
      description: "Start a new issue with initial task",
      icon: <Plus size={16} />,
      action: () => { setOpen(false); onCreateIssue?.(); },
      category: "action",
    },
    {
      id: "new-workspace",
      label: "Create New Workspace",
      description: "Set up a fresh workspace",
      icon: <Plus size={16} />,
      action: () => { setOpen(false); onCreateWorkspace?.(); },
      category: "action",
    },
    {
      id: "go-home",
      label: "Go to Home",
      description: "Navigate to home screen",
      icon: <Home size={16} />,
      action: () => { setOpen(false); router.push("/"); },
      category: "action",
    },
    {
      id: "go-settings",
      label: "Go to Settings",
      description: "Open settings page",
      icon: <Settings size={16} />,
      action: () => { setOpen(false); router.push("/settings"); },
      category: "action",
    },
  ], [onCreateIssue, onCreateWorkspace, router]);

  const filteredCommands = query
    ? commands.filter(
        (c) =>
          c.label.toLowerCase().includes(query.toLowerCase()) ||
          c.description?.toLowerCase().includes(query.toLowerCase())
      )
    : commands;

  const filteredBookmarks = query
    ? bookmarks.filter((b) => b.label.toLowerCase().includes(query.toLowerCase()))
    : bookmarks;

  const filteredHistory = query
    ? history.filter(
        (h) =>
          h.label.toLowerCase().includes(query.toLowerCase()) ||
          h.description?.toLowerCase().includes(query.toLowerCase())
      )
    : history;

  const activeItems =
    tab === "commands" ? filteredCommands : tab === "bookmarks" ? filteredBookmarks : filteredHistory;

  const handleSelect = (item: CommandItem | BookmarkItem | HistoryItem) => {
    item.action();
    setOpen(false);
  };

  const formatTime = (ts: number) => {
    const diff = Date.now() - ts;
    if (diff < 60000) return "just now";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return `${Math.floor(diff / 86400000)}d ago`;
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="p-0 gap-0 overflow-hidden border-border-subtle shadow-2xl" showCloseButton={false}>
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border-subtle bg-surface/50">
          <Search size={16} className="text-text-muted shrink-0" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search commands, bookmarks, history..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-text-muted outline-none"
          />
          <Kbd className="text-[10px]">ESC</Kbd>
        </div>

        <div className="flex items-center gap-1 px-3 py-2 border-b border-border-subtle bg-surface/30">
          {(["commands", "bookmarks", "history"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-black uppercase tracking-widest transition-all",
                tab === t
                  ? "bg-brand/10 text-brand"
                  : "text-text-muted hover:text-foreground hover:bg-surface-hover"
              )}
            >
              {t === "commands" && <Search size={12} />}
              {t === "bookmarks" && <Bookmark size={12} />}
              {t === "history" && <Clock size={12} />}
              {t}
            </button>
          ))}
        </div>

        <div className="max-h-[320px] overflow-y-auto p-2">
          {tab === "commands" && filteredCommands.length === 0 && (
            <p className="text-xs text-text-muted text-center py-8">No commands found</p>
          )}
          {tab === "bookmarks" && filteredBookmarks.length === 0 && (
            <p className="text-xs text-text-muted text-center py-8">No bookmarks yet. Bookmark issues or tasks for quick access.</p>
          )}
          {tab === "history" && filteredHistory.length === 0 && (
            <p className="text-xs text-text-muted text-center py-8">No recent activity</p>
          )}

          {tab === "commands" && filteredCommands.map((item) => (
            <button
              key={item.id}
              onClick={() => handleSelect(item)}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-surface-hover transition-colors group"
            >
              <div className="size-8 rounded-lg bg-surface-raised flex items-center justify-center text-text-muted group-hover:text-foreground">
                {item.icon}
              </div>
              <div className="flex-1 text-left">
                <p className="text-sm font-bold text-foreground">{item.label}</p>
                {item.description && (
                  <p className="text-[10px] text-text-muted">{item.description}</p>
                )}
              </div>
              <ChevronRight size={14} className="text-text-muted/40" />
            </button>
          ))}

          {tab === "bookmarks" && filteredBookmarks.map((item) => (
            <button
              key={item.id}
              onClick={() => handleSelect(item)}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-surface-hover transition-colors group"
            >
              <div className="size-8 rounded-lg bg-brand/10 flex items-center justify-center text-brand">
                {item.icon}
              </div>
              <div className="flex-1 text-left">
                <p className="text-sm font-bold text-foreground">{item.label}</p>
                <p className="text-[10px] text-text-muted uppercase tracking-widest">{item.type}</p>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); removeBookmark(item.id); }}
                className="p-1 rounded hover:bg-surface-raised text-text-muted hover:text-error"
              >
                <X size={12} />
              </button>
            </button>
          ))}

          {tab === "history" && filteredHistory.map((item) => (
            <button
              key={item.id}
              onClick={() => handleSelect(item)}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-surface-hover transition-colors group"
            >
              <div className="size-8 rounded-lg bg-surface-raised flex items-center justify-center text-text-muted group-hover:text-foreground">
                {item.icon}
              </div>
              <div className="flex-1 text-left">
                <p className="text-sm font-bold text-foreground">{item.label}</p>
                {item.description && (
                  <p className="text-[10px] text-text-muted">{item.description}</p>
                )}
              </div>
              <span className="text-[10px] text-text-muted">{formatTime(item.timestamp)}</span>
            </button>
          ))}
        </div>

        {tab === "history" && history.length > 0 && (
          <div className="px-3 py-2 border-t border-border-subtle">
            <button
              onClick={clearHistory}
              className="text-[10px] text-text-muted hover:text-error uppercase tracking-widest font-bold"
            >
              Clear History
            </button>
          </div>
        )}

        <div className="px-4 py-2 border-t border-border-subtle bg-surface/30 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="text-[10px] text-text-muted">
              <Kbd className="mr-1">↑↓</Kbd> navigate
            </span>
            <span className="text-[10px] text-text-muted">
              <Kbd className="mr-1">↵</Kbd> select
            </span>
          </div>
          <span className="text-[10px] text-text-muted">
            <Kbd>Ctrl</Kbd>+<Kbd>K</Kbd> toggle
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}